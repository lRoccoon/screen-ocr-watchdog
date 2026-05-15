(async function () {
  const resp = await fetch("messages.json");
  const data = await resp.json();
  const chat = document.getElementById("chat");
  const status = document.getElementById("status");
  const btnBurst = document.getElementById("btnBurst");
  const btnPause = document.getElementById("btnPause");

  const PERIOD_MS = 8000;
  let bodyIdx = 0;
  let paused = false;

  const pad2 = (n) => String(n).padStart(2, "0");
  const nowHHMM = () => {
    const d = new Date();
    return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  };
  const pickUser = () => data.users[Math.floor(Math.random() * data.users.length)];
  const nextBody = () => {
    const b = data.bodies[bodyIdx % data.bodies.length];
    bodyIdx++;
    return b;
  };
  const maybeQuote = () => (Math.random() < 0.25 ? data.quotes[Math.floor(Math.random() * data.quotes.length)] : null);

  function append(body, opts = {}) {
    const user = opts.user || pickUser();
    const quote = opts.quote ?? maybeQuote();

    const msg = document.createElement("div");
    msg.className = "msg";

    const row1 = document.createElement("div");
    row1.className = "row1";
    const av = document.createElement("div");
    av.className = "avatar";
    av.style.background = user.color;
    av.textContent = user.name.slice(-1);
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = user.name;
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = nowHHMM();
    row1.append(av, name, time);
    msg.append(row1);

    if (quote) {
      const q = document.createElement("div");
      q.className = "quote";
      q.textContent = `回复 ${quote}`;
      msg.append(q);
    }

    const bodyEl = document.createElement("div");
    bodyEl.className = "body";
    bodyEl.textContent = body;
    msg.append(bodyEl);

    chat.append(msg);
    chat.scrollTop = chat.scrollHeight;

    // 保留最近 30 条防止列表无限增长
    while (chat.children.length > 30) chat.removeChild(chat.firstChild);
  }

  function tick() {
    if (paused) return;
    append(nextBody());
  }

  function burst(n = 6) {
    for (let i = 0; i < n; i++) append(nextBody());
  }
  window.burst = burst;

  btnBurst.addEventListener("click", () => burst(6));
  btnPause.addEventListener("click", () => {
    paused = !paused;
    btnPause.textContent = paused ? "继续追加" : "暂停追加";
    status.textContent = paused ? "已暂停" : "运行中";
  });

  // 初始填充几条历史消息
  for (let i = 0; i < 3; i++) append(nextBody());
  setInterval(tick, PERIOD_MS);
})();
