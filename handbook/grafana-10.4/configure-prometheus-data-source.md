# Configure the Prometheus data source

Grafana ships with built-in support for Prometheus. Only users with the organization administrator role can add data sources and edit existing data sources.

## Configure the data source

To add the Prometheus data source:

1. Click **Connections** in the left-side menu.
2. Under **Connections**, click **Add new connection**.
3. Enter `Prometheus` in the search bar.
4. Select **Prometheus data source**.
5. Click **Create a Prometheus data source**.

## HTTP section

- **URL** - The URL of your Prometheus server. If your Prometheus server is local, use `http://localhost:9090`. If it is on a server within a network, this is the URL with port where you are running Prometheus. Example: `http://prometheus.example.orgname:9090`.
- **Timeout** - The HTTP request timeout. This must be in seconds.

## Auth section

- **Basic authentication** - Use your data source user name and data source password to connect.
- **TLS client authentication** - Toggle on to use client authentication.
- **Skip TLS verify** - Toggle on to bypass TLS certificate validation.

## Datasource connection failed

Datasource connection failed: check URL, credentials, and network to Prometheus.

If Grafana cannot reach Prometheus, verify the data source URL including protocol and port (default `9090`), that Prometheus is running and accepting connections, that credentials or TLS settings match the server, and that firewalls allow Grafana to connect. A timeout or connection refused points to networking; authentication failures often look like connection errors.
