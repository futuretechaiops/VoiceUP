const script = document.currentScript as HTMLScriptElement | null;
const agentId = script?.dataset.agentId ?? "preview-agent";

class ConciergeWidget extends HTMLElement {
  private open = false;

  connectedCallback(): void {
    const shadow = this.attachShadow({ mode: "open" });
    shadow.innerHTML = `
      <style>
        :host{position:fixed;right:24px;bottom:24px;z-index:2147483000;font-family:Inter,system-ui,sans-serif;color:#13251f}
        button{border:0;cursor:pointer;font:inherit}.launch{width:58px;height:58px;border-radius:50%;background:#154f3c;color:white;box-shadow:0 10px 30px #09291d44;font-size:22px}
        .panel{display:none;width:min(360px,calc(100vw - 32px));margin-bottom:12px;background:white;border:1px solid #dce5e0;border-radius:18px;box-shadow:0 18px 55px #0d281e30;overflow:hidden}
        .panel.open{display:block}.head{background:#123c30;color:white;padding:20px}.head strong{display:block;font-family:Georgia,serif;font-size:22px}.head small{color:#b9d1c8}
        .body{padding:20px}.notice{font-size:12px;line-height:1.5;color:#607068}.cta{width:100%;margin-top:18px;border-radius:9px;padding:12px;background:#cbed76;color:#153426;font-weight:700}
        .status{display:flex;align-items:center;gap:8px;font-size:13px}.dot{width:8px;height:8px;border-radius:50%;background:#54b487}
      </style>
      <section class="panel" role="dialog" aria-label="AI sales concierge">
        <div class="head"><strong>How can I help?</strong><small>AI sales concierge</small></div>
        <div class="body"><div class="status"><span class="dot"></span>Ready to start</div><p class="notice">This is an AI assistant. Your conversation may be processed to answer your enquiry. Microphone access is requested only after you start.</p><button class="cta">Start conversation</button></div>
      </section>
      <button class="launch" aria-label="Open AI sales concierge" aria-expanded="false">✦</button>`;
    const launch = shadow.querySelector<HTMLButtonElement>(".launch")!;
    const panel = shadow.querySelector<HTMLElement>(".panel")!;
    launch.addEventListener("click", () => {
      this.open = !this.open;
      panel.classList.toggle("open", this.open);
      launch.setAttribute("aria-expanded", String(this.open));
    });
    shadow.querySelector<HTMLButtonElement>(".cta")!.addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("concierge:start", { detail: { agentId }, bubbles: true }));
    });
  }
}

customElements.define("ai-sales-concierge", ConciergeWidget);
if (!document.querySelector("ai-sales-concierge")) document.body.append(document.createElement("ai-sales-concierge"));

