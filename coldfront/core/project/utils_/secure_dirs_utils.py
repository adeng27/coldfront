from coldfront.core.project.models import Project


def can_project_request_secure_dirs(project):
    """Return whether the given Project is eligible to request access to
    secure directories on the cluster."""
    if not isinstance(project, Project):
        raise TypeError(f'{project} is not a Project object.')
    return project.name.startswith('fc_')
