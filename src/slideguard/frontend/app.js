const fragment = new URLSearchParams(window.location.hash.slice(1));
const token = fragment.get("token");
history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);

const statusNode = document.querySelector("#status");
const exitButton = document.querySelector("#exit");

function apiFetch(path, options = {}) {
  return fetch(path, {
    ...options,
    cache: "no-store",
    headers: {
      ...(options.headers || {}),
      "X-SlideGuard-Token": token,
    },
  });
}

if (!token) {
  statusNode.textContent = "会话令牌缺失，请重新启动 SlideGuard。";
  exitButton.disabled = true;
} else {
  apiFetch("/api/health")
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(() => {
      statusNode.textContent = "本地服务连接成功。";
      const socketProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(
        `${socketProtocol}//${window.location.host}/ws`,
        ["slideguard", token],
      );
      socket.addEventListener("open", () => socket.send("ping"));
      socket.addEventListener("close", () => {
        statusNode.textContent = "本地服务连接已关闭。";
      });
    })
    .catch(() => {
      statusNode.textContent = "本地服务连接失败，请重新启动 SlideGuard。";
    });
}

exitButton.addEventListener("click", () => {
  exitButton.disabled = true;
  apiFetch("/api/exit", { method: "POST" })
    .then(() => {
      statusNode.textContent = "SlideGuard 正在退出…";
    })
    .catch(() => {
      statusNode.textContent = "退出请求失败，请直接关闭页面。";
      exitButton.disabled = false;
    });
});
