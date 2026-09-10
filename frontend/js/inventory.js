/* ==========================================================================
   RouteMind AI - depot stock cover and suggested transfers
   ========================================================================== */
(function () {
  "use strict";

  const RM = (window.RM = window.RM || {});

  RM.inventory = {
    data: null,

    async load() {
      try {
        this.data = await RM.api.inventory();
        this.render();
      } catch (err) {
        const body = RM.$("#inventory-table tbody");
        if (body) {
          body.innerHTML = '<tr><td colspan="4">' + RM.empty(err.message) + "</td></tr>";
        }
      }
    },

    render() {
      const body = RM.$("#inventory-table tbody");
      const transfers = RM.$("#transfer-list");
      if (!body || !this.data) return;

      const items = (this.data.items || []).slice().sort((a, b) => a.stock_days - b.stock_days);

      if (!items.length) {
        body.innerHTML = '<tr><td colspan="4">' + RM.empty("No stock records") + "</td></tr>";
      } else {
        body.innerHTML = items
          .map((item) => {
            const days = item.stock_days;
            const color =
              item.status === "shortage" || days <= 3 ? RM.color.crit
              : days <= 7 ? RM.color.warn
              : RM.color.ok;
            const width = Math.min(100, (days / 21) * 100);

            return (
              "<tr>" +
              "<td><div class='cell-main'>" + RM.esc(item.depot_name || item.depot_id) + "</div>" +
              "<div class='cell-sub'>" + RM.esc(item.city || "") + "</div></td>" +
              "<td>" + RM.esc(item.item) + "</td>" +
              '<td class="num"><span style="color:' + color + ';font-weight:600">' +
              RM.esc(days) + " days</span> " +
              '<span class="bar"><i style="width:' + width.toFixed(0) + "%;background:" + color + '"></i></span></td>' +
              "<td>" + this.statusPill(item.status, days) + "</td>" +
              "</tr>"
            );
          })
          .join("");
      }

      if (transfers) {
        const list = this.data.suggested_transfers || [];
        if (!list.length) {
          transfers.innerHTML =
            '<p class="muted small" style="padding:4px 2px">No transfers needed - every depot is inside its cover threshold.</p>';
        } else {
          transfers.innerHTML = list
            .map(
              (transfer) =>
                '<div class="transfer' + (transfer.urgency === "high" || transfer.urgency === "critical" ? " urgent" : "") + '">' +
                "<b>" + RM.esc(transfer.item) + "</b>" +
                '<p>Move from <b>' + RM.esc(transfer.from_depot) + "</b> to <b>" +
                RM.esc(transfer.to_depot) + "</b></p>" +
                '<p class="muted small" style="margin-top:4px">' + RM.esc(transfer.reason || "") + "</p>" +
                '<span class="pill ' + (transfer.urgency === "high" || transfer.urgency === "critical" ? "crit" : "warn") +
                '" style="margin-top:7px;display:inline-flex">' + RM.esc(RM.fmt.title(transfer.urgency || "planned")) +
                "</span></div>"
            )
            .join("");
        }
      }
    },

    statusPill(status, days) {
      if (status === "shortage" || days <= 3) return '<span class="pill crit">Shortage</span>';
      if (status === "low" || days <= 7) return '<span class="pill warn">Low cover</span>';
      if (status === "surplus") return '<span class="pill accent">Surplus</span>';
      return '<span class="pill ok">Healthy</span>';
    },
  };
})();
