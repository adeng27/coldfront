import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import IntegrityError
from django.db.models import BooleanField, Prefetch
from django.db.models.expressions import ExpressionWrapper, Q
from django.db.models.functions import Lower
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.urls import reverse_lazy
from django.utils.encoding import force_text
from django.utils.http import urlsafe_base64_decode
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView
from django.views.generic.edit import FormView

from coldfront.core.allocation.utils import has_cluster_access
from coldfront.core.project.models import Project, ProjectUser
from coldfront.core.user.models import IdentityLinkingRequest, IdentityLinkingRequestStatusChoice
from coldfront.core.user.models import UserProfile as UserProfileModel
from coldfront.core.user.forms import EmailAddressAddForm
from coldfront.core.user.forms import UserReactivateForm
from coldfront.core.user.forms import PrimaryEmailAddressSelectionForm
from coldfront.core.user.forms import UserAccessAgreementForm
from coldfront.core.user.forms import UserProfileUpdateForm
from coldfront.core.user.forms import UserRegistrationForm
from coldfront.core.user.forms import UserSearchForm, UserSearchListForm
from coldfront.core.user.models import EmailAddress
from allauth.account.models import EmailAddress as EmailAddress_LRC
from coldfront.core.user.utils import CombinedUserSearch
from coldfront.core.user.utils import ExpiringTokenGenerator
from coldfront.core.user.utils import send_account_activation_email
from coldfront.core.user.utils import send_account_already_active_email
from coldfront.core.user.utils import send_email_verification_email
from coldfront.core.user.utils import update_user_primary_email_address
from coldfront.core.user.utils_.host_user_utils import is_lbl_employee
from coldfront.core.utils.common import (import_from_settings,
                                         utc_now_offset_aware)

from flags.state import flag_enabled

logger = logging.getLogger(__name__)
EMAIL_ENABLED = import_from_settings('EMAIL_ENABLED', False)

if EMAIL_ENABLED:
    EMAIL_TICKET_SYSTEM_ADDRESS = import_from_settings(
        'EMAIL_TICKET_SYSTEM_ADDRESS')


@method_decorator(login_required, name='dispatch')
class UserProfile(TemplateView):
    template_name = 'user/user_profile.html'

    def dispatch(self, request, *args, viewed_username=None, **kwargs):
        # viewing another user profile requires permissions
        if viewed_username:
            if request.user.is_superuser or request.user.is_staff:
                # allow, via fallthrough
                pass
            else:
                # redirect them to their own profile

                # error if they tried to do something naughty
                if not request.user.username == viewed_username:
                    messages.error(request, "You aren't allowed to view other user profiles!")
                # if they used their own username, no need to provide an error - just redirect

                return HttpResponseRedirect(reverse('user-profile'))

        return super().dispatch(request, *args, viewed_username=viewed_username, **kwargs)

    def get_context_data(self, viewed_username=None, **kwargs):
        context = super().get_context_data(**kwargs)

        if viewed_username:
            viewed_user = get_object_or_404(User, username=viewed_username)
        else:
            viewed_user = self.request.user

        group_list = ', '.join(
            [group.name for group in viewed_user.groups.all()])
        context['group_list'] = group_list
        context['viewed_user'] = viewed_user

        context['has_cluster_access'] = has_cluster_access(viewed_user)

        requester_is_viewed_user = viewed_user == self.request.user

        if requester_is_viewed_user:
            self.update_context_with_identity_linking_request_data(context)

        context['help_email'] = import_from_settings('CENTER_HELP_EMAIL')

        # Only display the "Other Email Addresses" section for
        # coldfront.core.user.models.EmailAddress if basic auth. is enabled.
        is_basic_auth_enabled = flag_enabled('BASIC_AUTH_ENABLED')
        context['requester_is_viewed_user'] = requester_is_viewed_user
        context['primary_address_updatable'] = (
            is_basic_auth_enabled and requester_is_viewed_user)
        context['change_password_enabled'] = (
            is_basic_auth_enabled and requester_is_viewed_user)
        context['core_user_email_addresses_visible'] = is_basic_auth_enabled
        if context['core_user_email_addresses_visible']:
            context['other_emails'] = EmailAddress.objects.filter(
                user=viewed_user, is_primary=False).order_by('email')
            context['core_user_email_addresses_updatable'] = \
                requester_is_viewed_user

        # Only display the "Other Email Addresses" section for
        # allauth.account.models.EmailAddress if SSO is enabled.
        is_sso_enabled = flag_enabled('SSO_ENABLED')
        context['allauth_email_addresses_visible'] = is_sso_enabled
        if context['allauth_email_addresses_visible']:
            context['allauth_email_addresses_updatable'] = \
                requester_is_viewed_user

        # Only display the "Third-Party Accounts" section if SSO is enabled.
        context['third_party_accounts_visible'] = is_sso_enabled
        if context['third_party_accounts_visible']:
            context['third_party_accounts_updatable'] = \
                requester_is_viewed_user

        if flag_enabled('LRC_ONLY'):
            billing_id = 'N/A'
            try:
                user_profile = viewed_user.userprofile
            except UserProfileModel.DoesNotExist:
                message = (
                    f'User {viewed_user.username} unexpectedly has no '
                    f'UserProfile.')
                logger.error(message)
            else:
                billing_activity = user_profile.billing_activity
                if billing_activity:
                    billing_id = billing_activity.full_id()
            context['monthly_user_account_fee_billing_id'] = billing_id

        context['is_lbl_employee'] = is_lbl_employee(viewed_user)

        return context

    def update_context_with_identity_linking_request_data(self, context):
        """Update the given context dictionary with fields relating to
        IdentityLinkingRequests.

        In particular, set the key 'linking_request' to denote the
        latest request, whether it be complete, pending, or nonexistent.
        """
        user_requests = IdentityLinkingRequest.objects.filter(
            requester=self.request.user)
        pending_requests = user_requests.filter(
            status__name='Pending').order_by('request_time')
        complete_requests = user_requests.filter(
            status__name='Complete').order_by('completion_time')
        if pending_requests.exists():
            context['linking_request'] = pending_requests.last()
        elif complete_requests.exists():
            context['linking_request'] = complete_requests.last()
        else:
            context['linking_request'] = None


@method_decorator(login_required, name='dispatch')
class UserProfileUpdate(LoginRequiredMixin, FormView):
    form_class = UserProfileUpdateForm
    template_name = 'user/user_profile_update.html'
    success_url = reverse_lazy('user-profile')

    def form_valid(self, user_profile_update_form):
        user = self.request.user
        cleaned_data = user_profile_update_form.cleaned_data

        user.first_name = cleaned_data['first_name']
        user.last_name = cleaned_data['last_name']
        user.userprofile.middle_name = cleaned_data['middle_name']
        user.userprofile.phone_number = cleaned_data['phone_number']

        user.userprofile.save()
        user.save()

        messages.success(self.request, 'Details updated.')
        return super().form_valid(user_profile_update_form)

    def get_initial(self):
        user = self.request.user
        initial = super().get_initial()

        initial['first_name'] = user.first_name
        initial['middle_name'] = user.userprofile.middle_name
        initial['last_name'] = user.last_name
        initial['phone_number'] = user.userprofile.phone_number
        return initial


@method_decorator(login_required, name='dispatch')
class UserProjectsManagersView(ListView):
    template_name = 'user/user_projects_managers.html'

    def dispatch(self, request, *args, viewed_username=None, **kwargs):
        # viewing another user requires permissions
        if viewed_username:
            if request.user.is_superuser or request.user.is_staff:
                # allow, via fallthrough
                pass
            else:
                # redirect them to their own page

                # error if they tried to do something naughty
                if not request.user.username == viewed_username:
                    messages.error(request, "You aren't allowed to view projects for other users!")
                # if they used their own username, no need to provide an error - just redirect

                return HttpResponseRedirect(reverse('user-projects-managers'))

        # get_queryset does not get kwargs, so we need to store it off here
        if viewed_username:
            self.viewed_user = get_object_or_404(User, username=viewed_username)
        else:
            self.viewed_user = self.request.user

        return super().dispatch(request, *args, viewed_username=viewed_username, **kwargs)

    def get_queryset(self, *args, **kwargs):
        viewed_user = self.viewed_user

        ongoing_projectuser_statuses = (
            'Active',
            'Pending - Add',
            'Pending - Remove',
        )
        ongoing_project_statuses = (
            'New',
            'Active',
            'Inactive',
        )

        qs = ProjectUser.objects.filter(
            user=viewed_user,
            status__name__in=ongoing_projectuser_statuses,
            project__status__name__in=ongoing_project_statuses,
        ).select_related(
            'status',
            'role',
            'project',
            'project__status',
            'project__field_of_science',
        ).only(
            'status__name',
            'role__name',
            'project__title',
            'project__status__name',
            'project__field_of_science__description',
        ).annotate(
            is_project_pi=ExpressionWrapper(
                Q(role__name='Principal Investigator'),
                output_field=BooleanField(),
            ),
            is_project_manager=ExpressionWrapper(
                Q(role__name='Manager'),
                output_field=BooleanField(),
            ),
        ).order_by(
            '-is_project_pi',
            '-is_project_manager',
            Lower('project__title').asc(),
            # unlikely things will get to this point unless there's almost-duplicate projects
            '-project__pk',  # more performant stand-in for '-project__created'
        ).prefetch_related(
            Prefetch(
                lookup='project__projectuser_set',
                queryset=ProjectUser.objects.filter(
                    role__name='Principal Investigator',
                ).select_related(
                    'status',
                    'user',
                ).only(
                    'status__name',
                    'user__username',
                    'user__first_name',
                    'user__last_name',
                    'user__email',
                ).order_by(
                    'user__username',
                ),
                to_attr='project_pis',
            ),
            Prefetch(
                lookup='project__projectuser_set',
                queryset=ProjectUser.objects.filter(
                    role__name='Manager',
                    status__name__in=ongoing_projectuser_statuses,
                ).select_related(
                    'status',
                    'user',
                ).only(
                    'status__name',
                    'user__username',
                    'user__first_name',
                    'user__last_name',
                    'user__email',
                ).order_by(
                    'user__username',
                ),
                to_attr='project_managers',
            ),
        )

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['viewed_user'] = self.viewed_user

        if self.request.user == self.viewed_user:
            context['user_pronounish'] = 'You'
            context['user_verbform_be'] = 'are'
        else:
            context['user_pronounish'] = 'This user'
            context['user_verbform_be'] = 'is'

        return context


# class UserUpgradeAccount(LoginRequiredMixin, UserPassesTestMixin, View):
#
#     def test_func(self):
#         return True
#
#     def dispatch(self, request, *args, **kwargs):
#         if request.user.is_superuser:
#             messages.error(request, 'You are already a super user')
#             return HttpResponseRedirect(reverse('user-profile'))
#
#         if request.user.userprofile.is_pi:
#             messages.error(request, 'Your account has already been upgraded')
#             return HttpResponseRedirect(reverse('user-profile'))
#
#         return super().dispatch(request, *args, **kwargs)
#
#     def post(self, request):
#         if EMAIL_ENABLED:
#             profile = request.user.userprofile
#
#             # request already made
#             if profile.upgrade_request is not None:
#                 messages.error(request, 'Upgrade request has already been made')
#                 return HttpResponseRedirect(reverse('user-profile'))
#
#             # make new request
#             now = datetime.utcnow().astimezone(pytz.timezone(settings.TIME_ZONE))
#             profile.upgrade_request = now
#             profile.save()
#
#             send_email_template(
#                 'Upgrade Account Request',
#                 'email/upgrade_account_request.txt',
#                 {'user': request.user},
#                 request.user.email,
#                 [EMAIL_TICKET_SYSTEM_ADDRESS]
#             )
#
#         messages.success(request, 'Your request has been sent')
#         return HttpResponseRedirect(reverse('user-profile'))


class UserSearchHome(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'user/user_search_home.html'

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context['user_search_form'] = UserSearchForm()
        return context

    def test_func(self):
        return self.request.user.is_staff


class UserSearchAll(LoginRequiredMixin, ListView):
    model = User
    template_name = 'user/user_list.html'
    context_object_name = 'user_list'
    paginate_by = 25

    def test_func(self):
        if self.request.user.is_superuser or self.request.user.is_staff:
            return True

    def get_queryset(self):
        order_by = self.request.GET.get('order_by')
        if order_by:
            direction = self.request.GET.get('direction')
            if direction == 'asc':
                direction = ''
            else:
                direction = '-'
            order_by = direction + order_by
        else:
            order_by = 'id'

        user_search_form = UserSearchListForm(self.request.GET)

        if user_search_form.is_valid():
            data = user_search_form.cleaned_data
            users = User.objects.order_by(order_by)

            if data.get('first_name'):
                users = users.filter(first_name__icontains=data.get('first_name'))

            if data.get('middle_name'):
                users = users.filter(userprofile__middle_name__icontains=data.get('middle_name'))

            if data.get('last_name'):
                users = users.filter(last_name__icontains=data.get('last_name'))

            if data.get('username'):
                users = users.filter(username__icontains=data.get('username'))

            if flag_enabled('LRC_ONLY'):
                if data.get('email'):
                    _users = EmailAddress_LRC.objects.filter(is_primary=False, email__icontains=data.get('email'))\
                        .order_by('user').values_list('user__id')
                    users = users.filter(Q(email__icontains=data.get('email')) | Q(id__in=_users))
            else:
                if data.get('email'):
                    _users = EmailAddress.objects.filter(is_primary=False, email__icontains=data.get('email'))\
                        .order_by('user').values_list('user__id')
                    users = users.filter(Q(email__icontains=data.get('email')) | Q(id__in=_users))
        else:
            users = User.objects.all().order_by(order_by)

        return users.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_count = self.get_queryset().count()
        context['user_count'] = user_count

        user_search_form = UserSearchListForm(self.request.GET)
        if user_search_form.is_valid():
            context['user_search_form'] = user_search_form
            data = user_search_form.cleaned_data
            filter_parameters = ''

            for key, value in data.items():
                if value:
                    if isinstance(value, list):
                        for ele in value:
                            filter_parameters += '{}={}&'.format(key, ele)
                    else:
                        filter_parameters += '{}={}&'.format(key, value)
            context['user_search_form'] = user_search_form  # ??
        else:
            filter_parameters = None
            context['user_search_form'] = UserSearchListForm()

        order_by = self.request.GET.get('order_by')
        if order_by:
            direction = self.request.GET.get('direction')
            filter_parameters_with_order_by = filter_parameters + 'order_by=%s&direction=%s&' % (order_by, direction)
        else:
            filter_parameters_with_order_by = filter_parameters

        if filter_parameters:
            context['expand_accordion'] = 'show'

        context['filter_parameters'] = filter_parameters
        context['filter_parameters_with_order_by'] = filter_parameters_with_order_by

        user_list = context.get('user_list')
        paginator = Paginator(user_list, self.paginate_by)
        page = self.request.GET.get('page')

        try:
            user_list = paginator.page(page)
        except PageNotAnInteger:
            user_list = paginator.page(1)
        except EmptyPage:
            user_list = paginator.page(paginator.num_pages)

        return context

    def _filter_users_by_email(self, users, email):
        """Given a queryset of Users and an email address (str), return
        a filtered queryset of the given Users who are associated with
        the address."""
        pass


class UserSearchResults(LoginRequiredMixin, UserPassesTestMixin, View):
    template_name = 'user/user_search_results.html'
    raise_exception = True

    def post(self, request):
        user_search_string = request.POST.get('q')

        search_by = request.POST.get('search_by')

        cobmined_user_search_obj = CombinedUserSearch(
            user_search_string, search_by)
        context = cobmined_user_search_obj.search()

        return render(request, self.template_name, context)

    def test_func(self):
        return self.request.user.is_staff


class UserListAllocations(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'user/user_list_allocations.html'

    def test_func(self):
        return self.request.user.is_superuser or self.request.user.userprofile.is_pi

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        user_dict = {}

        project_pks = ProjectUser.objects.filter(
            user=self.request.user,
            role__name__in=['Manager', 'Principal Investigator'],
            status__name='Active').values_list('project', flat=True)
        for project in Project.objects.filter(pk__in=project_pks).distinct():
            for allocation in project.allocation_set.filter(status__name='Active'):
                for allocation_user in allocation.allocationuser_set.filter(status__name='Active').order_by('user__username'):
                    if allocation_user.user not in user_dict:
                        user_dict[allocation_user.user] = []

                    user_dict[allocation_user.user].append(allocation)

        context['user_dict'] = user_dict

        return context


class CustomPasswordChangeView(PasswordChangeView):

    template_name = 'user/passwords/password_change_form.html'
    success_url = reverse_lazy('user-profile')

    def form_valid(self, form):
        message = (
            'Your portal password has been changed. Note that you still need '
            'to use your PIN and OTP to access the cluster.')
        messages.success(self.request, message)
        return super().form_valid(form)


class UserLoginView(View):
    """Redirect to the Basic Auth. login view or the SSO login view
    based on enabled flags."""

    def dispatch(self, request, *args, **kwargs):
        basic_auth_enabled = 'BASIC_AUTH_ENABLED'
        if flag_enabled(basic_auth_enabled):
            return redirect(reverse('basic-auth-login'))
        sso_enabled = 'SSO_ENABLED'
        if flag_enabled(sso_enabled):
            return redirect(reverse('sso-login'))
        raise ImproperlyConfigured(
            f'One of the following flags must be enabled: '
            f'{basic_auth_enabled}, {sso_enabled}.')


class SSOLoginView(TemplateView):
    """Display the template for SSO login. If the user is authenticated,
    redirect to the home page."""
    template_name = 'user/sso_login.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(reverse('home'))
        return super().dispatch(request, *args, **kwargs)


class UserRegistrationView(CreateView):

    form_class = UserRegistrationForm
    template_name = 'user/registration.html'
    success_url = reverse_lazy('register')

    def form_valid(self, form):
        self.object = form.save()

        send_account_activation_email(self.object)
        message = (
            'Thank you for registering. Please click the link sent to your '
            'email address to activate your account.')
        messages.success(self.request, message)

        return HttpResponseRedirect(self.get_success_url())


class UserReactivateView(FormView):
    form_class = UserReactivateForm
    template_name = 'user/user_reactivate.html'

    logger = logging.getLogger(__name__)

    def form_valid(self, form):
        form_data = form.cleaned_data
        email = form_data['email']
        user = None
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            pass
        except User.MultipleObjectsReturned:
            self.logger.error(
                f'Unexpectedly found multiple Users with email address '
                f'{email}.')
            message = (
                'Unexpected server error. Please contact an administrator.')
            messages.error(self.request, message)
        if user:
            if user.is_active:
                send_account_already_active_email(user)
            else:
                send_account_activation_email(user)
        message = (
            'If the email address you entered is valid, please check the '
            'address for instructions to activate your account.')
        messages.success(self.request, message)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('login')


def activate_user_account(request, uidb64=None, token=None):
    try:
        user_pk = int(force_text(urlsafe_base64_decode(uidb64)))
        user = User.objects.get(pk=user_pk)
    except:
        user = None
    if user and token:
        if PasswordResetTokenGenerator().check_token(user, token):
            # Create or update an EmailAddress for the user's provided email.
            email = user.email.lower()
            try:
                email_address, created = EmailAddress.objects.get_or_create(
                    user=user, email=email)
                if created:
                    logger.info(
                        f'Created EmailAddress {email_address.pk} for User '
                        f'{user.pk} and email {email}.')
                email_address.is_verified = True
                email_address.save()
                update_user_primary_email_address(email_address)
            except Exception as e:
                logger.error(
                    f'Failed to create EmailAddress for User {user.pk} and '
                    f'email {email} and set it as the primary address. '
                    f'Details:')
                logger.exception(e)
                message = (
                    'Unexpected server error. Please contact an '
                    'administrator.')
                messages.error(request, message)
            else:
                # Only activate the User if the EmailAddress update succeeded.
                user.is_active = True
                user.save()
                message = (
                    f'Your account has been activated. You may now log in. '
                    f'{email} has been verified and set as your primary email '
                    f'address. You may modify this in the User Profile.')
                messages.success(request, message)
        else:
            message = (
                'Invalid activation token. Please try again, or contact an '
                'administrator if the problem persists.')
            messages.error(request, message)
    else:
        message = (
            'Failed to activate account. Please contact an administrator.')
        messages.error(request, message)
    return redirect(reverse('login'))


@login_required
def user_access_agreement(request):
    profile = request.user.userprofile
    if profile.access_agreement_signed_date is not None:
        message = 'You have already signed the user access agreement form.'
        messages.warning(request, message)
    if request.method == 'POST':
        form = UserAccessAgreementForm(request.POST)
        if form.is_valid():
            now = utc_now_offset_aware()
            profile.access_agreement_signed_date = now
            profile.save()
            message = 'Thank you for signing the user access agreement form.'
            messages.success(request, message)
            return redirect(reverse_lazy('home'))
        else:
            message = 'Incorrect answer. Please try again.'
            messages.error(request, message)
    else:
        form = UserAccessAgreementForm()

    if flag_enabled('BRC_ONLY'):
        template_name = 'user/deployments/brc/user_access_agreement.html'
    elif flag_enabled('LRC_ONLY'):
        template_name = 'user/deployments/lrc/user_access_agreement.html'
    else:
        raise ImproperlyConfigured(
            'One of the following flags must be enabled: BRC_ONLY, LRC_ONLY.')

    return render(request, template_name, context={'form': form})


class EmailAddressAddView(LoginRequiredMixin, FormView):
    form_class = EmailAddressAddForm
    template_name = 'user/user_add_email_address.html'

    logger = logging.getLogger(__name__)

    def form_valid(self, form):
        form_data = form.cleaned_data
        email = form_data['email']
        try:
            email_address = EmailAddress.objects.create(
                user=self.request.user, email=email, is_verified=False,
                is_primary=False)
        except IntegrityError:
            self.logger.error(
                f'EmailAddress {email} unexpectedly already exists.')
            message = (
                'Unexpected server error. Please contact an administrator.')
            messages.error(self.request, message)
        else:
            self.logger.info(
                f'Created EmailAddress {email_address.pk} for User '
                f'{self.request.user.pk}.')
            try:
                send_email_verification_email(email_address)
            except Exception as e:
                message = 'Failed to send verification email. Details:'
                logger.error(message)
                logger.exception(e)
                message = (
                    f'Added {email_address.email} to your account, but failed '
                    f'to send verification email. You may try to resend it '
                    f'from the User Profile.')
                messages.warning(self.request, message)
            else:
                message = (
                    f'Added {email_address.email} to your account. Please '
                    f'verify it by clicking the link sent to your email.')
                messages.success(self.request, message)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('user-profile')


class SendEmailAddressVerificationEmailView(LoginRequiredMixin, View):

    def dispatch(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')
        self.email_address = get_object_or_404(EmailAddress, pk=pk)
        if self.email_address.user != request.user:
            message = (
                'You may not send a verification email to an email address '
                'not associated with your account.')
            messages.error(request, message)
            return HttpResponseRedirect(reverse('user-profile'))
        if self.email_address.is_verified:
            logger.error(
                f'EmailAddress {self.email_address.pk} is unexpectedly '
                f'already verified.')
            message = f'{self.email_address.email} is already verified.'
            messages.warning(request, message)
            return HttpResponseRedirect(reverse('user-profile'))
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        try:
            send_email_verification_email(self.email_address)
        except Exception as e:
            message = 'Failed to send verification email. Details:'
            logger.error(message)
            logger.exception(e)
            message = (
                f'Failed to send verification email to '
                f'{self.email_address.email}. Please contact an administrator '
                f'if the problem persists.')
            messages.error(request, message)
        else:
            message = (
                f'Please click on the link sent to {self.email_address.email} '
                f'to verify it.')
            messages.success(request, message)
        return HttpResponseRedirect(reverse('user-profile'))


def verify_email_address(request, uidb64=None, eaidb64=None, token=None):
    try:
        user_pk = int(force_text(urlsafe_base64_decode(uidb64)))
        email_pk = int(force_text(urlsafe_base64_decode(eaidb64)))
        email_address = EmailAddress.objects.get(pk=email_pk)
        user = User.objects.get(pk=user_pk)
        if email_address.user != user:
            user = None
    except:
        user = None
    if user and token:
        if ExpiringTokenGenerator().check_token(user, token):
            email_address.is_verified = True
            email_address.save()
            logger.info(f'EmailAddress {email_address.pk} has been verified.')
            message = f'{email_address.email} has been verified.'
            messages.success(request, message)
        else:
            message = (
                'Invalid verification token. Please try again, or contact an '
                'administrator if the problem persists.')
            messages.error(request, message)
    else:
        message = (
            f'Failed to activate account. Please contact an administrator.')
        messages.error(request, message)
    return redirect(reverse('user-profile'))


class RemoveEmailAddressView(LoginRequiredMixin, View):

    def dispatch(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')
        self.email_address = get_object_or_404(EmailAddress, pk=pk)
        if self.email_address.user != request.user:
            message = (
                'You may not remove an email address not associated with your '
                'account.')
            messages.error(request, message)
            return HttpResponseRedirect(reverse('user-profile'))
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.email_address.delete()
        message = (
            f'{self.email_address.email} has been removed from your account.')
        messages.success(request, message)
        return HttpResponseRedirect(reverse('user-profile'))


class UpdatePrimaryEmailAddressView(LoginRequiredMixin, FormView):

    form_class = PrimaryEmailAddressSelectionForm
    template_name = 'user/user_update_primary_email_address.html'
    login_url = '/'

    error_message = 'Unexpected failure. Please contact an administrator.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['has_verified_non_primary_emails'] = \
            EmailAddress.objects.filter(
                user=self.request.user, is_verified=True, is_primary=False)
        return context

    def form_valid(self, form):
        user = self.request.user
        form_data = form.cleaned_data
        new_primary = form_data['email_address']

        try:
            update_user_primary_email_address(new_primary)
        except TypeError:
            message = (
                f'New primary EmailAddress {new_primary} has unexpected type: '
                f'{type(new_primary)}.')
            logger.error(message)
            messages.error(self.request, self.error_message)
        except ValueError:
            message = (
                f'New primary EmailAddress {new_primary.pk} for User '
                f'{user.pk} is unexpectedly not verified.')
            logger.error(message)
            messages.error(self.request, self.error_message)
        except Exception as e:
            message = (
                f'Encountered unexpected exception when updating User '
                f'{user.pk}\'s primary EmailAddress to {new_primary.pk}. '
                f'Details:')
            logger.error(message)
            logger.exception(e)
            messages.error(self.request, self.error_message)
        else:
            message = f'{new_primary.email} is your new primary email address.'
            messages.success(self.request, message)

        return super().form_valid(form)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse('user-profile')


class EmailAddressExistsView(View):

    def get(self, request, *args, **kwargs):
        email_address_exists = EmailAddress.objects.filter(
            email=self.kwargs.get('email').lower()).exists()
        return JsonResponse({'email_address_exists': email_address_exists})


class UserNameExistsView(View):

    def get(self, request, *args, **kwargs):
        first_name = request.GET.get('first_name', None)
        middle_name = request.GET.get('middle_name', None)
        last_name = request.GET.get('last_name', None)
        if not (first_name or middle_name or last_name):
            return JsonResponse({'error': 'No names provided.'})
        users = User.objects.all()
        if first_name is not None:
            users = users.filter(first_name__iexact=first_name)
        if last_name is not None:
            users = users.filter(last_name__iexact=last_name)
        if middle_name is not None:
            users = users.filter(userprofile__middle_name__iexact=middle_name)
        return JsonResponse({'name_exists': users.exists()})


@method_decorator(login_required, name='dispatch')
class IdentityLinkingRequestView(UserPassesTestMixin, View):
    login_url = '/'
    pending_status = None

    def test_func(self):
        return True

    def dispatch(self, request, *args, **kwargs):
        self.pending_status = IdentityLinkingRequestStatusChoice.objects.get(
            name='Pending')
        user = self.request.user
        redirection = HttpResponseRedirect(reverse('user-profile'))

        if not has_cluster_access(user):
            message = (
                'You do not have active cluster access. Please gain access to '
                'the cluster before attempting to request a linking email.')
            messages.error(request, message)
            return redirection

        pending_requests_for_user = IdentityLinkingRequest.objects.filter(
            requester=user, status=self.pending_status)
        if pending_requests_for_user.exists():
            message = (
                'You have already requested a linking email. Please wait '
                'until it has been sent to request another.')
            messages.error(request, message)
            return redirection

        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        user = request.user
        identity_linking_request = IdentityLinkingRequest.objects.create(
            requester=user,
            status=self.pending_status,
            request_time=utc_now_offset_aware())
        logger.info(
            f'User {user.pk} created IdentityLinkingRequest '
            f'{identity_linking_request.pk} to be sent to {user.email}.')

        message = (
            f'A request has been generated. An email will be sent to '
            f'{user.email} shortly.')
        messages.success(request, message)

        return HttpResponseRedirect(reverse('user-profile'))
