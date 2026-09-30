import type { SigningRequest } from "./types";
import { formatDate, PanelTitle, StatusBadge } from "./ui";

const mutedText = "muted";

export function Timeline({ request }: { request: SigningRequest }) {
  const events = request.signers
    .flatMap((signer) => signer.events.map((event) => ({ ...event, signer })))
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  return (
    <section className="timeline" aria-label="Immutable signer event timeline">
      <PanelTitle>Timeline</PanelTitle>
      {events.map((event) => (
        <article key={event.id}>
          <span className="timeline-dot" />
          <div className="timeline-event">
            <strong>{event.signer.name}</strong>
            <StatusBadge status={event.status} />
            <small className={mutedText}>{event.actor_name} - {formatDate(event.created_at)}</small>
            {event.note && <p>{event.note}</p>}
          </div>
        </article>
      ))}
    </section>
  );
}

