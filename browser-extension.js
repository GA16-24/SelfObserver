async function push() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab) return;
  try {
    await fetch("http://127.0.0.1:8765/ingest", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({title: tab.title || "", url: tab.url || ""})
    });
  } catch (e) {}
}

chrome.tabs.onUpdated.addListener((id, info, tab) => {
  if (info.status === "complete") push();
});

chrome.tabs.onActivated.addListener(push);
setInterval(push, 5000);
