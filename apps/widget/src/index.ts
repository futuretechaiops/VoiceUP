/**
 * AI Sales Concierge widget (text). One async script tag:
 *   <script async src=".../widget.js" data-agent-id="agt_..." data-api-base="https://api..."></script>
 * Everything lives in a Shadow DOM so the host page's CSS cannot break it and it cannot break
 * the host page. No cookies or storage are used; the session token lives in memory only.
 */

const script = document.currentScript as HTMLScriptElement | null;
const agentId = script?.dataset.agentId ?? "";
// Default: the API that served this script, so one script tag is all a site owner needs.
const scriptOrigin = script?.src ? new URL(script.src, location.href).origin : "http://localhost:8000";
const apiBase = (script?.dataset.apiBase ?? scriptOrigin).replace(/\/$/, "");

interface SessionInfo {
  session_id: string;
  token: string;
  agent_name: string;
  notice: string;
  consent_text: string;
  privacy_url: string | null;
}

interface Reply {
  reply: string;
  sources: { title: string; url: string }[];
  offer_lead_form: boolean;
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
form.chat{display:none;gap:8px;padding:10px;border-top:1px solid #e3ebe7}
form.chat.on{display:flex}
input{flex:1;border:1px solid #c9d6cf;border-radius:9px;padding:10px;font:inherit}
.send{border:0;border-radius:9px;padding:0 14px;background:#154f3c;color:#fff}
.send:disabled{opacity:.5;cursor:default}
.sources{align-self:flex-start;font-size:12px;color:#44564e;display:flex;flex-direction:column;gap:2px;max-width:85%}
.sources a{color:#154f3c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.callback{background:none;border:0;color:#154f3c;text-decoration:underline;font-size:12px;padding:6px 10px;text-align:left}
.lead{display:none;flex-direction:column;gap:8px;padding:12px;border-top:1px solid #e3ebe7;background:#f8faf9;overflow:auto;max-height:70%}
.lead.on{display:flex}.lead strong{font-size:14px}
.lead label{font-size:12px;display:flex;flex-direction:column;gap:3px}
.lead .consent{flex-direction:row;gap:8px;align-items:flex-start;line-height:1.35}
.lead .consent input{flex:none;margin-top:2px}
.lead .hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.lead .row{display:flex;gap:8px}.lead .row button{flex:1;border-radius:9px;padding:10px;border:0}
.lead .go{background:#154f3c;color:#fff}.lead .skip{background:#e3ebe7}
.lead .err{color:#7a1c14;font-size:12px;min-height:1em}
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
        <button class="callback" type="button" hidden>Request a call back</button>
        <form class="lead" aria-label="Request a call back" novalidate>
          <strong>Request a call back</strong>
          <label>Your name<input name="name" maxlength="120" autocomplete="name" required></label>
          <label>Phone number<input name="phone" type="tel" maxlength="40" autocomplete="tel" required></label>
          <label>Email<input name="email" type="email" maxlength="254" autocomplete="email" required></label>
          <label class="hp" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
          <label class="consent"><input name="consent" type="checkbox"><span class="consent-text"></span></label>
          <div class="err" role="alert"></div>
          <div class="row"><button class="go" type="submit">Send my details</button><button class="skip" type="button">Not now</button></div>
        </form>
        <form class="chat" aria-label="Send a message"><input name="text" maxlength="1000" autocomplete="off" aria-label="Your message" placeholder="Type your question…"><button class="send" type="submit">Send</button></form>
      </section>
      <button class="launch" aria-label="Open AI sales concierge" aria-expanded="false">✦</button>`;

    const q = <T extends HTMLElement>(sel: string): T => root.querySelector<T>(sel) as T;
    const launch = q<HTMLButtonElement>(".launch");
    const panel = q<HTMLElement>(".panel");
    const body = q<HTMLElement>(".body");
    const form = q<HTMLFormElement>("form.chat");
    const lead = q<HTMLFormElement>("form.lead");
    const callback = q<HTMLButtonElement>(".callback");
    const input = q<HTMLInputElement>("form.chat input");
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

    let leadDone = false;
    const showLead = () => {
      if (leadDone || !this.session) return;
      (lead.querySelector(".consent-text") as HTMLElement).textContent = this.session.consent_text;
      lead.classList.add("on");
      form.classList.remove("on");
      callback.hidden = true;
      (lead.querySelector("input[name=name]") as HTMLInputElement).focus();
    };
    const hideLead = () => {
      lead.classList.remove("on");
      form.classList.add("on");
      callback.hidden = leadDone;
    };
    callback.addEventListener("click", showLead);
    q<HTMLButtonElement>(".skip").addEventListener("click", hideLead);
    lead.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!this.session) return;
      const f = new FormData(lead);
      const err = lead.querySelector(".err") as HTMLElement;
      const val = (k: string) => String(f.get(k) ?? "").trim();
      if (!val("name") || !val("phone") || !val("email")) {
        err.textContent = "Please fill in your name, phone number and email.";
        return;
      }
      if (!f.get("consent")) {
        err.textContent = "Please tick the box so we may contact you.";
        return;
      }
      err.textContent = "";
      const go = lead.querySelector(".go") as HTMLButtonElement;
      go.disabled = true;
      try {
        const res = await fetch(`${apiBase}/api/v1/public/widget/session/${this.session.session_id}/lead`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${this.session.token}` },
          body: JSON.stringify({
            name: val("name"), phone: val("phone"), email: val("email"),
            consent: true, website: val("website"),
          }),
        });
        if (res.status === 422) {
          err.textContent = "Please check your phone number and email address.";
          return;
        }
        if (res.status === 429) {
          err.textContent = "Too many attempts. Please try again later.";
          return;
        }
        if (!res.ok) {
          err.textContent = "Sorry, we could not send your details. Please try again.";
          return;
        }
        leadDone = true;
        lead.reset();
        hideLead();
        add("agent", "Thank you. I've passed your details to the team and they will be in touch.");
      } catch {
        err.textContent = "Connection problem. Please try again.";
      } finally {
        go.disabled = false;
      }
    });

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
        callback.hidden = false;
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
        const data = (await res.json()) as Reply;
        add("agent", data.reply);
        if (data.sources?.length) {
          const box = document.createElement("div");
          box.className = "sources";
          box.append("Sources:");
          for (const src of data.sources.slice(0, 3)) {
            let url: URL;
            try {
              url = new URL(src.url);
            } catch {
              continue;
            }
            if (url.protocol !== "https:" && url.protocol !== "http:") continue;
            const a = document.createElement("a");
            a.href = url.href;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = src.title || url.href;
            box.append(a);
          }
          body.append(box);
        }
        if (data.offer_lead_form && !leadDone) {
          showLead();
          body.scrollTop = body.scrollHeight;
        }
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
