// Service worker of the test site: sends its own request with a consent parameter after
// activation, to see whether capture.py sees requests of service workers.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim().then(() => fetch("/px?gdpr=1&gdpr_consent=SERVICE_WORKER_GET")));
});
