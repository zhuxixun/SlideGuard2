const fragment = new URLSearchParams(window.location.hash.slice(1));
const token = fragment.get("token");
history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);

const statusNode = document.querySelector("#status");

if (!token) {
  statusNode.textContent = "会话令牌缺失，请重新启动 SlideGuard。";
} else {
  fetch("/api/health", {
    headers: { "X-SlideGuard-Token": token },
    cache: "no-store",
  })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(() => {
      statusNode.textContent = "本地服务连接成功。";
    })
    .catch(() => {
      statusNode.textContent = "本地服务连接失败，请重新启动 SlideGuard。";
    });
