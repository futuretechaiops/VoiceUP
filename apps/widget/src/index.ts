/**
 * AI Sales Concierge widget (text). One async script tag:
 *   <script async src=".../widget.js" data-agent-id="agt_..." data-api-base="https://api..."></script>
 * Everything lives in a Shadow DOM so the host page's CSS cannot break it and it cannot break
 * the host page. No cookies or storage are used; the session token lives in memory only.
 */

const script = document.currentScript as HTMLScriptElement | null;
const agentId = script?.dataset.agentId ?? "";
const apiBase = (script?.dataset.apiBase ?? "http://localhost:8000").replace(/\/$/, "");

interface SessionInfo {
  session_id: string;
  token: string;
  agent_name: string;
  notice: string;
}

const STYLE = `
:host{position:fixed;right:24px;bottom:24px;z-index:2147483000;font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;color:#13251f}
*{box-sizing:border-box}button{font:inherit;cursor:pointer}
.launch{width:58px;height:58px;border-radius:50%;border:0;background:#154f3c;color:#fff;font-size:22px;box-shadow:0 10px 30px #09291d44}
.launch:focus-visible,.send:focus-visible,.cta:focus-visible,.close:focus-visible,input:focus-visible{outline:3px solid #cbed76;outline-offset:2px}
.panel{display:none;flex-direction:column;width:min(380px,calc(100vw - 32px));height:min(520px,calc(100vh - 120px));margin-bottom:12px;background:#fff;border:1px solid #dce5e0;border-radius:18px;box-shadow:0 18px 55px #0d281e30;overflow:hidden}
.panel.open{display:flex}
.head{background:#123c30;color:#fff;padding:14px 16px;display:flex;justify-content:space-between;align-items:center}
.head strong{display:block;font-size:16px}.head small{color:#b9d1c8}
.close{background:none;border:0;color:#fff;font-size:20px;line-height:1}
.body{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:8px}
.notice{font-size:12px;color:#44564e;background:#f2f6f4;border-radius:10px;padding:10px}
.msg{max-width:85%;padding:9px 12px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word}
.msg.visitor{align-self:flex-end;background:#154f3c;color:#fff}
.msg.agent{align-self:flex-start;background:#eef3f0}
.msg.error{align-self:center;background:#fdecea;color:#7a1c14;font-size:13px}
.cta{margin:auto 0 0;border:0;border-radius:9px;padding:12px;background:#cbed76;color:#153426;font-weight:700}
form{display:none;gap:8px;padding:10px;border-top:1px solid #e3ebe7}
form.on{display:flex}
input{flex:1;border:1px solid #c9d6cf;border-radius:9px;padding:10px;font:inherit}
.send{border:0;border-radius:9px;padding:0 14px;background:#154f3c;color:#fff}
.send:disabled{opacity:.5;cursor:default}
`;

class ConciergeWidget extends HTMLElement {
  private session: SessionInfo | null = null;
  private busy = false;

  connectedCallback(): void {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${STYLE}</style>
      <section class="panel" role="dialog" aria-label="AI sales concierge" aria-live="polite">
        <div class="head"><div><strong>How can I help?</strong><small>AI sales concierge</small></div>
          <button class="close" aria-label="Close chat">×</button></div>
        <div class="body" role="log" aria-label="Conversation">
          <p class="notice">You are chatting with an AI assistant, not a person. Messages are processed to answer your enquiry.</p>
          <button class="cta" type="button">Start conversation</button>
        </div>
        <form aria-label="Send a message"><input name="text" maxlength="1000" autocomplete="off" aria-label="Your message" placeholder="Type your question…"><button class="send" type="submit">Send</button></form>
      </section>
      <button class="launch" aria-label="Open AI sales concierge" aria-expanded="false">✦</button>`;

    const q = <T extends HTMLElement>(sel: string): T => root.querySelector<T>(sel) as T;
    const launch = q<HTMLButtonElement>(".launch");
    const panel = q<HTMLElement>(".panel");
    const body = q<HTMLElement>(".body");
    const form = q<HTMLFormElement>("form");
    const input = q<HTMLInputElement>("input");
    const send = q<HTMLButtonElement>(".send");
    const cta = q<HTMLButtonElement>(".cta");

    const setOpen = (open: boolean) => {
      panel.classList.toggle("open", open);
      launch.setAttribute("aria-expanded", String(open));
      if (open) (this.session ? input : cta).focus();
      else launch.focus();
    };
    const add = (cls: string, text: string) => {
      const el = document.createElement("div");
      el.className = `msg ${cls}`;
      el.textContent = text; // never innerHTML: replies are untrusted text
      body.append(el);
      body.scrollTop = body.scrollHeight;
    };

    launch.addEventListener("click", () => setOpen(!panel.classList.contains("open")));
    q<HTMLButtonElement>(".close").addEventListener("click", () => setOpen(false));
    panel.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "Escape") setOpen(false);
    });

    cta.addEventListener("click", async () => {
      cta.disabled = true;
      cta.textContent = "Connecting…";
      try {
        const res = await fetch(`${apiBase}/api/v1/public/widget/session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent_id: agentId }),
        });
        if (!res.ok) throw new Error(res.status === 403 ? "forbidden" : "unavailable");
        this.session = (await res.json()) as SessionInfo;
        cta.remove();
        form.classList.add("on");
        add("agent", `Hello, I'm ${this.session.agent_name}, an AI assistant. How can I help?`);
        input.focus();
      } catch (err) {
        cta.disabled = false;
        cta.textContent = "Start conversation";
        add(
          "error",
          (err as Error).message === "forbidden"
            ? "This website is not approved to use this assistant."
            : "The assistant is unavailable right now. Please try again later.",
        );
      }
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text || !this.session || this.busy) return;
      this.busy = true;
      send.disabled = true;
      input.value = "";
      add("visitor", text);
      try {
        const res = await fetch(`${apiBase}/api/v1/public/widget/session/${this.session.session_id}/events`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${this.session.token}` },
          body: JSON.stringify({ type: "message", text }),
        });
        if (res.status === 429) throw new Error("You're sending messages too quickly. Please wait a moment.");
        if (res.status === 401 || res.status === 409) throw new Error("This conversation has ended. Close and reopen to start again.");
        if (!res.ok) throw new Error("Sorry, something went wrong. Please try again.");
        add("agent", ((await res.json()) as { reply: string }).reply);
      } catch (err) {
        add("error", err instanceof Error && err.message.length < 120 && !/fetch/i.test(err.message)
          ? err.message
          : "Connection problem. Please try again.");
      } finally {
        this.busy = false;
        send.disabled = false;
        input.focus();
      }
    });
  }
}

if (!agentId) {
  console.warn("[concierge] data-agent-id is missing; widget not started.");
} else if (!customElements.get("ai-sales-concierge")) {
  customElements.define("ai-sales-concierge", ConciergeWidget);
  const mount = () => {
    if (!document.querySelector("ai-sales-concierge")) document.body.append(document.createElement("ai-sales-concierge"));
  };
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
}
