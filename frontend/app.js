// Frontend logic. Owner: frontend person. API shapes: see CONTRACT.md

// Via nginx (docker) use relative /api; opened as a file, talk to the backend directly
const API = location.protocol === "file:" ? "http://localhost:8000/api" : "/api";

const $ = (id) => document.getElementById(id);

async function checkHealth() {
  try {
    const r = await fetch(`${API}/health`);
    const data = await r.json();
    $("api-status").textContent = `${data.status} (v${data.version})`;
  } catch {
    $("api-status").textContent = "offline — is the backend running?";
  }
}

$("predict-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("error").hidden = true;
  try {
    const r = await fetch(`${API}/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: $("input-text").value }),
    });
    if (!r.ok) throw new Error(`Server error ${r.status}`);
    const data = await r.json();
    $("result-label").textContent = data.label;
    $("result-score").textContent = Math.round(data.score * 100) + "%";
    $("result-explanation").textContent = data.explanation;
    $("result-model").textContent = `model: ${data.model}`;
    $("result").hidden = false;
  } catch (err) {
    $("error").textContent = err.message;
    $("error").hidden = false;
  }
});

checkHealth();
