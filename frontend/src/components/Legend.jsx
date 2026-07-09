export default function Legend({ renderedLayer }) {
  if (!renderedLayer) return null;

  const min = Number(renderedLayer.vmin).toFixed(2);
  const max = Number(renderedLayer.vmax).toFixed(2);
  const unit = renderedLayer.unit || "";
  const sourceVariables = renderedLayer.source_variables?.length
    ? renderedLayer.source_variables.join(", ")
    : renderedLayer.source_variable;
  const methodLabel = formatMethod(renderedLayer.combination_method);

  return (
    <div className="legend">
      <div className="legend-title">
        <span>{renderedLayer.label}</span>
        <small>{unit || "value"}</small>
      </div>

      <div className={`legend-gradient ${renderedLayer.layer}`} />

      <div className="legend-values">
        <span>{min} {unit}</span>
        <span>{max} {unit}</span>
      </div>

      <div className="legend-source">
        {methodLabel} · {sourceVariables}
      </div>
    </div>
  );
}

function formatMethod(method) {
  if (method === "sum") return "Summed layer";
  if (method === "mean") return "Mean layer";
  if (method === "vector") return "Vector magnitude";
  if (method === "index") return "Composite index";
  return "Combined layer";
}
