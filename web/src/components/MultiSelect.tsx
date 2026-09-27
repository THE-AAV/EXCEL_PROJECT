import { useEffect, useRef, useState } from "react";

export default function MultiSelect({ label, options, value, onChange }: {
  label: string;
  options: string[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  if (!options.length) return null;
  const shown = options.filter((o) => o.toLowerCase().includes(text.toLowerCase()));
  const toggle = (o: string) => onChange(value.includes(o) ? value.filter((v) => v !== o) : [...value, o]);

  return (
    <div className="multi" ref={ref}>
      <label className="field-label">{label}</label>
      <button type="button" className="multi-button" onClick={() => setOpen(!open)}>
        {value.length === 0 ? "All" : value.length === 1 ? value[0] : `${value.length} selected`}
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="multi-menu">
          {options.length > 8 && (
            <input autoFocus className="search" placeholder="Find…" value={text} onChange={(e) => setText(e.target.value)} />
          )}
          <div className="multi-list">
            {shown.map((o) => (
              <label key={o} className="multi-item">
                <input type="checkbox" checked={value.includes(o)} onChange={() => toggle(o)} /> {o}
              </label>
            ))}
          </div>
          {value.length > 0 && <button className="link" onClick={() => onChange([])}>Clear</button>}
        </div>
      )}
    </div>
  );
}
