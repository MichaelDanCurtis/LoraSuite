import { ArrowLeft, RefreshCw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  resetKey: string;
  onBack(): void;
  onReload(): void;
  onOpenStudio(): void;
};

export class GuidedErrorBoundary extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) { return { error }; }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Guided workspace failed", error, info);
  }

  componentDidUpdate(previous: Props) {
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    const moduleFailed = /dynamically imported module|loading chunk|module script/i.test(this.state.error.message);
    return (
      <section className="guided-runtime-error" role="alert">
        <h2>{moduleFailed ? "This workspace couldn’t load" : "This workspace needs attention"}</h2>
        <p>{moduleFailed
          ? "The connection may have dropped or the app may have updated. Reload to try again, or return to your project."
          : "Return to your project to choose another step, or reload to try again."}</p>
        <div className="guided-runtime-error-actions">
          <button className="primary-action" type="button" onClick={() => {
            this.props.onBack();
            this.setState({ error: null });
          }}><ArrowLeft size={16} aria-hidden="true" /> Back to project</button>
          <button type="button" onClick={this.props.onReload}><RefreshCw size={16} aria-hidden="true" /> Reload workspace</button>
        </div>
        <details><summary>Error details</summary><pre>{this.state.error.message}</pre></details>
        <button className="guided-runtime-error-advanced" type="button" onClick={this.props.onOpenStudio}>Open Advanced Consoles</button>
      </section>
    );
  }
}
