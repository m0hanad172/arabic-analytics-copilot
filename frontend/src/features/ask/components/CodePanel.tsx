import { useMemo, useState } from "react";
import { format as formatSql } from "sql-formatter";

// Syntax highlighter (Prism)
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

function tryPrettyJson(text: string) {
  try {
    const obj = JSON.parse(text);
    return JSON.stringify(obj, null, 2);
  } catch {
    return null;
  }
}

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function CodePanel({
  title,
  text,
  kind = "text",
}: {
  title: string;
  text: string;
  kind?: "sql" | "json" | "text";
}) {
  const [wrap, setWrap] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [lineNums, setLineNums] = useState(true);
  const [copied, setCopied] = useState(false);

  const pretty = useMemo(() => {
    if (!text) return "";

    if (kind === "json") {
      return tryPrettyJson(text) ?? text;
    }

    if (kind === "sql") {
      try {
        return formatSql(text, { language: "postgresql" });
      } catch {
        return text;
      }
    }

    return text;
  }, [text, kind]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(pretty);
      setCopied(true);
      setTimeout(() => setCopied(false), 900);
    } catch {}
  };

  const ext = kind === "sql" ? "sql" : kind === "json" ? "json" : "txt";
  const language = kind === "sql" ? "sql" : kind === "json" ? "json" : "text";

  return (
    <div className="codebox" dir="ltr">
      {/* ✅ واحد فقط: Header + toolbar */}
      <div className="codehead px-3 py-2 d-flex justify-content-between align-items-center gap-2 flex-wrap">
        <div className="d-flex align-items-center gap-2">
          <div className="fw-semibold">{title}</div>
          <span className="badge text-bg-secondary">{kind.toUpperCase()}</span>
          {copied && <span className="badge text-bg-success">Copied</span>}
        </div>

        <div className="d-flex gap-2">
          <button
            className="btn btn-outline-secondary btn-sm"
            onClick={() => setLineNums((v) => !v)}
            title="Line numbers"
            type="button"
          >
            <i className="bi bi-list-ol" />
          </button>

          <button
            className="btn btn-outline-secondary btn-sm"
            onClick={() => setWrap((v) => !v)}
            title="Wrap"
            type="button"
          >
            <i className={`bi ${wrap ? "bi-text-wrap" : "bi-text-paragraph"}`} />
          </button>

          <button
            className="btn btn-outline-secondary btn-sm"
            onClick={() => setExpanded((v) => !v)}
            title="Expand"
            type="button"
          >
            <i className={`bi ${expanded ? "bi-arrows-angle-contract" : "bi-arrows-angle-expand"}`} />
          </button>

          <button className="btn btn-outline-secondary btn-sm" onClick={copy} title="Copy" type="button">
            <i className="bi bi-copy" />
          </button>

          <button
            className="btn btn-outline-secondary btn-sm"
            onClick={() => downloadText(`${title}.${ext}`, pretty)}
            title="Download"
            type="button"
          >
            <i className="bi bi-download" />
          </button>
        </div>
      </div>

      <div
        className="p-2"
        style={{
          maxHeight: expanded ? 900 : 520,
          overflow: "auto",
          borderTop: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        {/* ✅ مهم: لا نطلع <pre>/<code> عشان Prism toolbar ما يركّب نفسه */}
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          showLineNumbers={lineNums}
          wrapLongLines={wrap}
          PreTag="div"
          CodeTag="div"
          customStyle={{
            margin: 0,
            background: "transparent",
            fontSize: 13,
            lineHeight: 1.7,
          }}
          lineNumberStyle={{
            opacity: 0.55,
            minWidth: "3em",
            paddingRight: "12px",
          }}
        >
          {pretty}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}
