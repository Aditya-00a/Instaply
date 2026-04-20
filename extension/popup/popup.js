// Tiny status popup. Shows whether the active tab is a supported ATS
// page so the user can confirm the extension is alive before they
// trigger a fill from the Instaply dashboard.

async function refresh() {
  const status = document.getElementById("status");
  let url = "";
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    url = (tabs[0] && tabs[0].url) || "";
  } catch (_) {
    /* permission may be denied on some pages */
  }
  if (/job-boards\.greenhouse\.io|boards\.greenhouse\.io/.test(url)) {
    status.textContent = "Greenhouse application page detected. Trigger a fill from your Instaply dashboard.";
    status.className = "status ok";
  } else if (/jobs\.lever\.co/.test(url)) {
    status.textContent = "Lever application page detected. Trigger a fill from your Instaply dashboard.";
    status.className = "status ok";
  } else {
    status.textContent = "Open a supported job page (Greenhouse or Lever) to use Instaply here.";
    status.className = "status idle";
  }
}
refresh();
