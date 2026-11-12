(() => {
  const blocks = [...document.querySelectorAll(".doc-content pre > code.language-mermaid")];
  if (!blocks.length) return;

  async function renderDiagrams() {
    try {
      const { default: mermaid } = await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs");
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: document.documentElement.dataset.theme === "dark" ? "dark" : "default",
        themeVariables: { fontSize: "18px" },
      });

      const diagrams = blocks.map((code) => {
        const source = code.parentElement;
        const figure = document.createElement("figure");
        figure.className = "doc-diagram";
        const diagram = document.createElement("div");
        diagram.className = "mermaid";
        diagram.setAttribute("role", "img");
        diagram.setAttribute("aria-label", "Architecture diagram");
        diagram.textContent = code.textContent;

        const details = document.createElement("details");
        details.className = "doc-diagram-source";
        const summary = document.createElement("summary");
        summary.textContent = "View diagram source";
        source.replaceWith(figure);
        details.append(summary, source);
        figure.append(diagram, details);
        return diagram;
      });

      await mermaid.run({ nodes: diagrams });
      for (const diagram of diagrams) {
        const svg = diagram.querySelector("svg");
        const viewBox = svg?.getAttribute("viewBox")?.trim().split(/[\s,]+/).map(Number);
        if (!svg || !viewBox || viewBox.length !== 4 || !Number.isFinite(viewBox[2]) || viewBox[2] <= 0) continue;

        svg.style.width = `${Math.ceil(viewBox[2])}px`;
        svg.style.maxWidth = "none";
        const hint = document.createElement("p");
        hint.className = "doc-diagram-hint";
        hint.textContent = "Scroll horizontally to explore the full diagram.";
        diagram.before(hint);
      }
    } catch (error) {
      console.error("Could not render the architecture diagram; the source remains available.", error);
      for (const code of blocks) {
        const figure = code.closest(".doc-diagram");
        if (!figure) continue;
        const status = document.createElement("p");
        status.className = "doc-diagram-error";
        status.textContent = "Diagram preview is unavailable. Open “View diagram source” to read its text.";
        figure.prepend(status);
      }
    }
  }

  renderDiagrams();
})();
