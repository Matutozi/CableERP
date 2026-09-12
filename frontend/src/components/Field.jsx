/** A labelled form control. Pass as="div" when the children contain their own <label>. */
export default function Field({ label, hint, wide = false, as: Tag = "label", children }) {
  return (
    <Tag className={wide ? "field field-wide" : "field"}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </Tag>
  );
}
