/* LEGEND CUSTOM CAMPAIGNS V1
 * Independent campaign manager. Legacy GTA VI / Expedia modes are untouched.
 * Nothing here automatically posts, downloads or re-renders videos.
 * This classic script loads before main index.html JS, and is used afterwards.
 */
"use strict";

async function loadCampaigns() {
  const rows = await api("/api/custom-campaigns");
  if (!Array.isArray(rows)) throw new Error("Could not load campaigns.");
  S.campaigns = rows;
  if (S.view === "campaigns") drawCampaigns();
  return rows;
}

function drawCampaigns() {
  const root = $("#campaigns-page");
  if (!root) return;
  const campaigns = S.campaigns || [];
  const active = campaigns.filter(x => x.status === "active").length;
  const projects = S.jobs.filter(j => j.options?.custom_campaign_id && campaigns.some(c => c.id === j.options.custom_campaign_id));
  const summary = '<div class="lc-campaign-summary"><div class="lc-c-stat"><b>' + campaigns.length +
    '</b><small>Total campaigns</small></div><div class="lc-c-stat"><b>' + active +
    '</b><small>Active</small></div><div class="lc-c-stat"><b>' + projects.length +
    '</b><small>Clip jobs linked</small></div></div>';
  const header = '<div class="lc-c-intro"><div><h2>Custom Campaigns</h2><p>Create a campaign for a brand or project, set its default copy and use it when making new clips. Completely separate from GTA 6 Auto Clipping.</p></div><button class="btn primary" data-campaign-action="new">' + ic("plus") + 'New campaign</button></div>';
  if (!campaigns.length) {
    root.innerHTML = header + summary + '<div class="lc-c-empty"><div class="lc-c-empty-icon">' + ic("folder") + '</div><h3>No campaigns yet</h3><p>Create your first campaign to keep branded clips and hashtags organized. Nothing will be auto-posted.</p><button class="btn primary" data-campaign-action="new">' + ic("plus") + 'Create campaign</button></div>';
    return;
  }
  root.innerHTML = header + summary + '<div class="lc-c-grid">' + campaigns.map(c => {
    const jobList = S.jobs.filter(j => j.options?.custom_campaign_id === c.id);
    const done = jobList.reduce((n,j) => n + (j.clips||[]).filter(x => x.status === "done").length, 0);
    const tags = (c.hashtags || []).map(t => '<span class="lc-c-tag">#'+esc(t)+'</span>').join("");
    return '<article class="lc-c-card"><div class="lc-c-top"><span class="lc-c-state '+(c.status==="active"?"active":"paused")+'">'+(c.status==="active"?"Active":"Paused")+'</span><span class="lc-c-muted">Created '+new Date(c.created*1000).toLocaleDateString()+'</span></div>'+
      '<h3>'+esc(c.name)+'</h3><div class="lc-c-brand">'+esc(c.brand || "Personal campaign")+'</div>'+
      '<p class="lc-c-brief">'+esc(c.brief || "No brief added yet.")+'</p>'+
      (c.hook_text ? '<p class="lc-c-preview"><b>Big text:</b> '+esc(c.hook_text)+'</p>':"")+
      '<div class="lc-c-tags">'+(tags||'<span class="lc-c-muted">No custom hashtags</span>')+'</div>'+
      '<div class="lc-c-meta"><span>'+jobList.length+' video job'+(jobList.length===1?"":"s")+'</span><span>'+done+' finished clip'+(done===1?"":"s")+'</span></div>'+
      '<div class="lc-c-actions"><button class="btn primary sm" data-campaign-action="use" data-id="'+esc(c.id)+'" '+(c.status==="active"?"":"disabled")+'>'+ic("scissors")+'Use for clips</button><button class="btn sm" data-campaign-action="edit" data-id="'+esc(c.id)+'">'+ic("cog")+'Edit</button><button class="btn sm" data-campaign-action="toggle" data-id="'+esc(c.id)+'">'+(c.status==="active"?"Pause":"Activate")+'</button><button class="btn sm danger" data-campaign-action="delete" data-id="'+esc(c.id)+'" title="Delete campaign">'+ic("trash")+'</button></div></article>';
  }).join("")+'</div><p class="lc-c-footnote">Campaign rates are reference notes only, not tracked revenue or guaranteed payouts. Review usage rights and brand rules before publishing. Deleting a campaign leaves previously created clip jobs intact.</p>';
}

function openCampaignEditor(campaign) {
  const dlg = $("#formdlg");
  const c = campaign || {};
  dlg.innerHTML = '<form method="dialog" class="dlg lc-c-dialog">'+
    '<h2>'+ (campaign ? 'Edit campaign' : 'New custom campaign')+'</h2>'+
    '<p class="help">Organize branded clips. Campaign text applies only to future clips when you select this campaign.</p>'+
    '<label class="f">Campaign name <input id="lc_cm_name" required maxlength="85" value="'+esc(c.name || "")+'" placeholder="e.g. Minecraft Creator Launch"></label>'+
    '<label class="f">Brand / client (optional) <input id="lc_cm_brand" maxlength="90" value="'+esc(c.brand || "")+'" placeholder="Brand name"></label>'+
    '<label class="f">Campaign brief / requirements <textarea id="lc_cm_brief" rows="3" maxlength="1500" placeholder="Goal, what makes a good clip, rules to review…">'+esc(c.brief || "")+'</textarea></label>'+
    '<label class="f">Big text on every clip (optional, 60 characters) <input id="lc_cm_hook" maxlength="60" value="'+esc(c.hook_text || "")+'" placeholder="Leave blank for AI-generated hooks"></label>'+
    '<label class="f">Description on every clip (optional) <textarea id="lc_cm_desc" rows="3" maxlength="2000" placeholder="Leave blank for the AI description">'+esc(c.description_text || "")+'</textarea></label>'+
    '<label class="f">Hashtags <input id="lc_cm_tags" value="'+esc((c.hashtags||[]).map(t=>"#"+t).join(" "))+'" placeholder="#gaming #shorts"></label>'+
    '<div class="lc-c-form-row"><label class="f">Status <select id="lc_cm_status"><option value="active" '+(c.status==="paused"?"":"selected")+'>Active</option><option value="paused" '+(c.status==="paused"?"selected":"")+'>Paused</option></select></label>'+
    '<label class="f">Reference rate per 1K views ($) <input id="lc_cm_rate" type="number" min="0" max="100000" step="0.01" value="'+esc(c.rate_per_1k ?? 0)+'"></label></div>'+
    '<p class="help">This does not create a payment arrangement, verify compliance, or post anything automatically.</p>'+
    '<div class="dlg-foot"><button class="btn" value="cancel" formnovalidate>Cancel</button><button class="btn primary" value="save">Save campaign</button></div>'+
    '</form>';
  dlg.returnValue = "cancel";
  dlg.onclose = async () => {
    if (dlg.returnValue !== "save") return;
    const body = {
      name: $("#lc_cm_name")?.value || "", brand: $("#lc_cm_brand")?.value || "",
      brief: $("#lc_cm_brief")?.value || "", hook_text: $("#lc_cm_hook")?.value || "",
      description_text: $("#lc_cm_desc")?.value || "", hashtags: $("#lc_cm_tags")?.value || "",
      status: $("#lc_cm_status")?.value || "active", rate_per_1k: Number($("#lc_cm_rate")?.value || 0)
    };
    try {
      const endpoint = campaign ? "/api/custom-campaigns/" + encodeURIComponent(campaign.id) : "/api/custom-campaigns";
      await send(endpoint, body, campaign ? "PUT" : "POST");
      await loadCampaigns();
      toast("Campaign saved successfully.", "ok");
    } catch (err) {
      toast("Could not save campaign: " + err.message, "bad");
      // Keep form values so the user can correct an invalid field and retry.
      if (dlg.isConnected) dlg.showModal();
    }
  };
  dlg.showModal();
  $("#lc_cm_name")?.focus();
}

document.addEventListener("click", async e => {
  const b = e.target.closest("[data-campaign-action]");
  if (!b) return;
  e.preventDefault();
  const action = b.dataset.campaignAction;
  const selected = (S.campaigns || []).find(c => c.id === b.dataset.id);
  try {
    if (action === "new") return openCampaignEditor(null);
    if (!selected) throw new Error("Campaign was not found; refresh the page.");
    if (action === "edit") return openCampaignEditor(selected);
    if (action === "use") {
      if (selected.status !== "active") throw new Error("Activate this campaign before using it.");
      S.campaignChoice = selected.id;
      go("overview");
      const btn = $('[data-act="toggleopts"]');
      if (btn && !$(".composer-opts")?.classList.contains("open")) btn.click();
      toast("Selected " + selected.name + ". Add a video link or upload a file.", "ok");
      return;
    }
    if (action === "toggle") {
      await send("/api/custom-campaigns/" + encodeURIComponent(selected.id),
                 {status:selected.status==="active"?"paused":"active"}, "PUT");
      if (selected.status === "active" && S.campaignChoice === selected.id) S.campaignChoice = "";
      await loadCampaigns();
      toast("Campaign status updated.", "ok");
      return;
    }
    if (action === "delete") {
      if (!await ask("Delete " + selected.name + "?", "The campaign definition will be removed. Completed clips and jobs remain unchanged. This cannot be undone.", "Delete campaign", true)) return;
      await api("/api/custom-campaigns/" + encodeURIComponent(selected.id), {method:"DELETE"});
      if (S.campaignChoice === selected.id) S.campaignChoice = "";
      await loadCampaigns();
      toast("Campaign removed. Existing clips were preserved.", "ok");
    }
  } catch(err) { toast(err.message, "bad"); }
});

document.addEventListener("change", e => {
  if (e.target.id === "o_custom_campaign") {
    S.campaignChoice = e.target.value;
  }
});
