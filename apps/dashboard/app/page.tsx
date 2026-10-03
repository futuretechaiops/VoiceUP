const metrics = [
  ["Conversations", "0"],
  ["Qualified leads", "0"],
  ["Appointments", "0"],
  ["Conversion", "—"],
] as const;

export default function Dashboard() {
  return (
    <main>
      <aside>
        <div className="brand"><span>AC</span> Concierge Control</div>
        <nav aria-label="Main navigation">
          {['Overview', 'Agents', 'Knowledge', 'Conversations', 'Leads', 'Integrations', 'Settings'].map((item, index) => (
            <a className={index === 0 ? 'active' : ''} href="#" key={item}>{item}</a>
          ))}
        </nav>
        <div className="tenant">Development workspace<br/><small>Customer administrator</small></div>
      </aside>
      <section className="content">
        <header>
          <div><p className="eyebrow">OVERVIEW</p><h1>Good evening</h1><p>Build, test and operate your sales concierge.</p></div>
          <button>New agent</button>
        </header>
        <div className="metrics">
          {metrics.map(([label, value]) => <article key={label}><p>{label}</p><strong>{value}</strong><small>Awaiting first session</small></article>)}
        </div>
        <div className="grid">
          <article className="panel">
            <div className="panelHead"><div><p className="eyebrow">GET STARTED</p><h2>Launch your first concierge</h2></div><span>0 / 4</span></div>
            {['Define the agent identity and goals', 'Connect approved website knowledge', 'Test the conversation and qualification flow', 'Publish the widget on an approved domain'].map((step, i) => (
              <div className="step" key={step}><b>{i + 1}</b><span>{step}</span><em>Not started</em></div>
            ))}
          </article>
          <article className="panel health">
            <p className="eyebrow">PLATFORM</p><h2>Foundation status</h2>
            <div><span>API</span><b>Ready</b></div>
            <div><span>Tenant isolation</span><b>Protected</b></div>
            <div><span>Knowledge</span><b className="muted">Next work package</b></div>
            <div><span>Realtime voice</span><b className="muted">Planned</b></div>
          </article>
        </div>
      </section>
    </main>
  );
}

