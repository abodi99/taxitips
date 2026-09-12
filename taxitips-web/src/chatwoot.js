import { chatwoot as chatwootConfig } from "./config.js";

let booted = false;

/**
 * Loads the Chatwoot website widget. Safe to call before consent —
 * chat is a support channel, not marketing analytics.
 */
export function initChatwoot() {
  if (booted || !chatwootConfig.websiteToken) return;
  booted = true;

  window.chatwootSettings = {
    position: "right",
    locale: "sv",
    type: "standard",
    launcherTitle: "Chatta med oss",
  };

  const script = document.createElement("script");
  script.src = `${chatwootConfig.baseUrl}/packs/js/sdk.js`;
  script.defer = true;
  script.async = true;
  script.onload = () => {
    window.chatwootSDK?.run({
      websiteToken: chatwootConfig.websiteToken,
      baseUrl: chatwootConfig.baseUrl,
    });
  };
  document.body.appendChild(script);
}
