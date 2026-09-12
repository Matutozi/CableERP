const PATHS = {
  dashboard: (
    <>
      <rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1" />
      <rect x="9" y="2.5" width="4.5" height="4.5" rx="1" />
      <rect x="2.5" y="9" width="4.5" height="4.5" rx="1" />
      <rect x="9" y="9" width="4.5" height="4.5" rx="1" />
    </>
  ),
  quotes: (
    <>
      <path d="M9.5 1.5H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5z" />
      <path d="M9.5 1.5V5H13M5.5 8.5h5M5.5 11h3" />
    </>
  ),
  catalogue: (
    <>
      <path d="M8 1.8l6 3.1-6 3.1-6-3.1z" />
      <path d="M2 8.1l6 3.1 6-3.1M2 11.2l6 3.1 6-3.1" />
    </>
  ),
  settings: (
    <>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M3.4 12.6l1.3-1.3M11.3 4.7l1.3-1.3" />
    </>
  ),
  logout: (
    <>
      <path d="M6 2.5H3.5a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1H6" />
      <path d="M10 5l3 3-3 3M13 8H6.5" />
    </>
  ),
  trash: <path d="M3 4h10M6.5 4V2.8h3V4M4.5 4l.6 9h5.8l.6-9" />,
  plus: <path d="M8 3.5v9M3.5 8h9" />,
  back: <path d="M10 3L5 8l5 5" />,
  chevron: <path d="M4 6l4 4 4-4" />,
};

export default function Icon({ name, size = 16, strokeWidth = 1.5 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}
