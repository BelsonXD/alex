import type { Approval } from "../types";

export function ApprovalDialog({
  approval,
  onDecide,
}: {
  approval: Approval;
  onDecide: (approved: boolean) => void;
}) {
  return (
    <div className="modal-back" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="approval-title">
        <p className="eyebrow">Host clearance</p>
        <h2 id="approval-title">Approve this action</h2>
        <p className="tool-name">{approval.tool}</p>
        <p className="risk">{approval.risk}</p>
        <pre>{approval.summary}</pre>
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={() => onDecide(false)}>
            Deny
          </button>
          <button type="button" className="solid" onClick={() => onDecide(true)}>
            Approve once
          </button>
        </div>
      </section>
    </div>
  );
}
