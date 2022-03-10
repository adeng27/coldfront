from coldfront.core.project.models import Project
from coldfront.core.project.utils_.permissions_utils import is_user_manager_or_pi_of_project
from coldfront.core.project.utils_.secure_dirs_utils import can_project_request_secure_dirs
from coldfront.core.user.utils import access_agreement_signed

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic.base import TemplateView

import logging

"""Views relating to making requests for access to secure directories on
the cluster."""


logger = logging.getLogger(__name__)


class SecureDirectoriesRequestLandingView(LoginRequiredMixin,
                                          UserPassesTestMixin, TemplateView):
    """A view that provides information regarding requesting access to
    secure directories for the given Project. Eligible Project types
    include: FCA."""

    template_name = 'project/project_secure_dirs/request_landing.html'
    login_url = '/'

    project_obj = None

    def dispatch(self, request, *args, **kwargs):
        """Store the Project object for reuse. If it is ineligible,
        redirect."""
        pk = self.kwargs.get('pk')
        self.project_obj = get_object_or_404(Project, pk=pk)

        if not can_project_request_secure_dirs(self.project_obj):
            message = (
                f'Project {self.project_obj.name} is ineligible to request '
                f'access to secure directories.')
            messages.error(request, message)
            return HttpResponseRedirect(
                reverse('project-detail', kwargs={'pk': self.project_obj.pk}))

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Set the following variables:
            TODO
        """
        context = super().get_context_data(**kwargs)
        context['project'] = self.project_obj
        # TODO
        return context

    def test_func(self):
        """Allow superusers and users with permission to view
        SecureDirectoriesCreateRequests. Allow active PIs and Managers
        of the Project who have signed the User Access Agreement."""
        user = self.request.user
        permission = '' # TODO
        if user.is_superuser or user.has_perm(permission):
            return True
        if not access_agreement_signed(user):
            message = 'You must sign the User Access Agreement.'
            messages.error(self.request, message)
            return False
        if is_user_manager_or_pi_of_project(user, self.project_obj):
            return True
        message = 'You must be an active PI or manager of the Project.'
        messages.error(self.request, message)


class SecureDirectoriesRequestView(LoginRequiredMixin, UserPassesTestMixin):
    pass
