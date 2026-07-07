const tabs = ["Data Ingress", "Curate / Search", "Video Review", "Exports"];

function App() {
  return (
    <main className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">LoraSuite</p>
          <h1>Dataset Workspace</h1>
        </div>
      </header>

      <nav className="tab-bar" aria-label="Workspace sections">
        {tabs.map((tab, index) => (
          <button
            className={index === 0 ? "tab active" : "tab"}
            type="button"
            key={tab}
          >
            {tab}
          </button>
        ))}
      </nav>

      <section className="workspace-panel" aria-label="Active workspace">
        <h2>Data Ingress</h2>
      </section>
    </main>
  );
}

export default App;
