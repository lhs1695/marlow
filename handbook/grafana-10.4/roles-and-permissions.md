# Roles and permissions

A user is any individual who can log in to Grafana. Each user is associated with a role that includes permissions. Permissions determine the tasks a user can perform in the system. For example, the Admin role includes permissions for an administrator to create and delete users.

You can assign a user one of three types of permissions:

- Grafana server administrator permissions: Manage Grafana server-wide settings and resources
- Organization permissions: Manage access to dashboards, alerts, plugins, teams, playlists, and other resources for an entire organization. The available roles are Viewer, Editor, and Admin.
- Dashboard and folder permission: Manage access to dashboards and folders

## Organization roles

Grafana uses the following roles to control user access:

- **Organization administrator (Admin)**: Has access to all organization resources, including dashboards, users, and teams. Can add, edit, and delete data sources.
- **Editor**: Can view and edit dashboards, folders, and playlists.
- **Viewer**: Can view dashboards, playlists, and query data sources.

Roles: Viewer, Editor, Admin. Privilege changes need an administrator. Organization role-based permissions are global within a given organization unless a dashboard restricts them.
