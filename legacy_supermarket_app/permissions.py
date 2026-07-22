# Admin and analyst both get unrestricted, all-branch access; analyst is just a
# separate login/label for the same permission level.
FULL_ACCESS_ROLES = ("admin", "analyst")


def has_role(user, *roles):
    return user.role in roles
