/* Empty state — design.md §Wireframes.
 *
 * The four starter cards are not decoration. Each maps to a distinct skill
 * path (A, B, C, and a comparative Q&A), so the first interaction teaches the
 * user what the system can actually do rather than leaving them to guess at a
 * blank box. `skill` is passed through as `skill_override`, which is exactly
 * what §5.7 documents that field for. */

const STARTERS = [
  {
    skill: null,
    title: 'Ask a question about retention loops',
    prompt: 'What makes a retention loop work, and where do most teams get it wrong?',
    hint: 'Grounded Q&A',
  },
  {
    skill: 'ship30',
    title: 'Write a Ship30for30 essay on PMF',
    prompt: 'Write a Ship30for30 essay on how to know when you have product-market fit',
    hint: '~1,250 words',
  },
  {
    skill: 'artifact',
    title: 'Build a metrics dashboard mockup',
    prompt: 'Build me an HTML dashboard mockup for weekly cohort retention',
    hint: 'Renders live',
  },
  {
    skill: null,
    title: 'Compare B2B and B2C growth loops',
    prompt: 'How do growth loops differ between B2B and B2C, according to the guests?',
    hint: 'Cross-episode',
  },
]

export function EmptyState({ onPick, chunks, dbConnected }) {
  const corpusEmpty = dbConnected && chunks === 0

  return (
    <div className="empty">
      <div className="empty__mark" aria-hidden="true">
        ◆
      </div>
      <h1 className="empty__title">The Lenny Growth Assistant</h1>
      <p className="empty__sub">
        Grounded in Lenny&rsquo;s Podcast transcripts.
        {chunks > 0 && (
          <>
            {' '}
            <span className="empty__count">{chunks.toLocaleString()} passages indexed.</span>
          </>
        )}
      </p>

      {corpusEmpty ? (
        <div className="notice notice--warning empty__notice" role="status">
          <strong>The vector store is empty.</strong>
          <p>
            Answers are grounded in the transcript corpus, and nothing has been ingested yet.
            Run this from <code>backend/</code>:
          </p>
          <pre>
            <code>python -m app.cli ingest --source github</code>
          </pre>
        </div>
      ) : (
        <div className="empty__cards">
          {STARTERS.map((s) => (
            <button
              key={s.title}
              type="button"
              className="startcard"
              onClick={() => onPick(s.prompt, s.skill)}
            >
              <span className="startcard__title">{s.title}</span>
              <span className="startcard__hint">{s.hint}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
