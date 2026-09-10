/* ==========================================================================
   RouteMind AI - alert inbox
   Backend statuses: new | acknowledged | assigned | escalated | resolved
   Backend actions:  acknowledge | assign | escalate | resolve
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});
  const OPERATOR = "Duty dispatcher";

  RM.alerts = {
    render() {
      const host = RM.$("#alert-list");
      if (!host) return;

      const alerts = RM.state.alerts || [];
      if (!alerts.length) {
        host.innerHTML = RM.empty("No alerts. The network is quiet.");
        return;
      }

      const rank = { critical: 0, high: 1, warning: 2, info: 3 };
      const sorted = alerts.slice().sort((a, b) => {
        const resolvedA = a.status === "resolved" ? 1 : 0;
        const resolvedB = b.status === "resolved" ? 1 : 0;
        if (resolvedA !== resolvedB) return resolvedA - resolvedB;
        const ra = rank[a.severity] === undefined ? 4 : rank[a.severity];
        const rb = rank[b.severity] === undefined ? 4 : rank[b.severity];
        if (ra !== rb) return ra - rb;
        return (b.created_at || 0) - (a.created_at || 0);
      });

      host.innerHTML = sorted.map((alert) => this.card(alert)).join("");

      RM.$$("#alert-list [data-action]").forEach((btn) => {
        btn.addEventListener("click", () =>
          this.act(btn.dataset.alert, btn.dataset.action)
        );
      });
    },

    card(alert) {
      const unread = alert.status === "new";
      const severityPill =
        alert.severity === "critical" ? '<span class="pill crit">Critical</span>'
        : alert.severity === "high" ? '<span class="pill warn">High</span>'
        : alert.severity === "warning" ? '<span class="pill warn">Warning</span>'
        : '<span class="pill soft">Info</span>';

      const statusPill =
        alert.status === "resolved" ? '<span class="pill ok">Resolved</span>'
        : alert.status === "escalated" ? '<span class="pill crit">Escalated</span>'
        : alert.status === "assigned" ? '<span class="pill accent">Assigned</span>'
        : alert.status === "acknowledged" ? '<span class="pill soft">Acknowledged</span>'
        : '<span class="pill dark">New</span>';

      const buttons = [];
      if (alert.status === "new") {
        buttons.push(this.button(alert.id, "acknowledge", "Acknowledge", "ghost"));
      }
      if (alert.status !== "resolved") {
        if (alert.status !== "assigned") buttons.push(this.button(alert.id, "assign", "Assign to me", "ghost"));
        if (alert.status !== "escalated") buttons.push(this.button(alert.id, "escalate", "Escalate", "ghost"));
        buttons.push(this.button(alert.id, "resolve", "Resolve", "primary"));
      }

      const related = alert.related || {};

      return (
        '<div class="alert-item' + (unread ? " unread" : "") + '">' +
        '<div class="alert-main">' +
        '<div class="alert-title">' + RM.esc(alert.title) + severityPill + statusPill + "</div>" +
        '<div class="alert-body">' + RM.esc(alert.body || "") + "</div>" +
        '<div class="alert-meta">' + RM.esc(RM.timeAgo(alert.created_at)) +
        (alert.assignee ? " - assigned to " + RM.esc(alert.assignee) : "") +
        (related.corridor_id ? " - " + RM.esc(related.corridor_id) : "") +
        "</div></div>" +
        '<div class="alert-actions">' + buttons.join("") + "</div>" +
        "</div>"
      );
    },

    button(id, action, label, style) {
      return (
        '<button class="btn tiny ' + style + '" data-alert="' + RM.esc(id) +
        '" data-action="' + action + '">' + label + "</button>"
      );
    },

    async act(alertId, action) {
      try {
        await RM.api.alertAction(alertId, action, action === "assign" ? OPERATOR : undefined);
        RM.toast("Alert " + action + "d", "ok");
        await RM.app.refresh();
      } catch (err) {
        RM.toast(err.message, "err");
      }
    },

    async acknowledgeAll() {
      try {
        await RM.api.acknowledgeAll();
        RM.toast("All alerts acknowledged", "ok");
        await RM.app.refresh();
      } catch (err) {
        RM.toast(err.message, "err");
      }
    },
  };
})();
