import { defineRailway, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const scamflowAiVolume = volume("scamflow-ai-volume", {
    alerts: { usage: { "80": {}, "95": {}, "100": {} } },
    allowOnlineResize: true,
    region: "sfo",
    sizeMB: 500,
  });
  const scamflowAi = service("scamflow-ai", {
    replicas: { "sfo": 1 },
    healthcheck: "/health",
    healthcheckTimeout: 300,
    volumeMounts: { "/data": scamflowAiVolume },
    env: {
      SCAMFLOW_ASSESSMENT_TIMEOUT_SECONDS: preserve(),
      SCAMFLOW_CASE_RETENTION_SECONDS: preserve(),
      SCAMFLOW_DATABASE_PATH: preserve(),
      SCAMFLOW_ENVIRONMENT: preserve(),
      SCAMFLOW_LOG_LEVEL: preserve(),
      SCAMFLOW_SECURE_COOKIES: preserve(),
      SCAMFLOW_SESSION_TTL_SECONDS: preserve(),
      SCAMFLOW_SQLITE_BUSY_TIMEOUT_MS: preserve(),
      SCAMFLOW_TRUSTED_ORIGIN: preserve(),
    },
  });

  return project("scamflow-ai", {
    resources: [scamflowAi, scamflowAiVolume],
  });
});
