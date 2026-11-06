# Grafana with our datasource + dashboard built in (used on Rahti; locally the folders are mounted).
FROM grafana/grafana:11.3.0
COPY grafana/provisioning /etc/grafana/provisioning
COPY grafana/dashboards /etc/grafana/dashboards
ENV GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/etc/grafana/dashboards/compactor.json
