import type { CascadeResult } from '../lib/api'
import { num } from '../lib/format'

/** Renders the five cascade stages, each with the numbers that produced it. */
export default function CascadePanel({ result }: { result: CascadeResult }) {
  const h = result.headline
  const [gap, refinery, price, sector, macro] = result.stages as never as [
    Record<string, never>, Record<string, never>, Record<string, never>,
    Record<string, never>, Record<string, never>,
  ]

  return (
    <>
      <div className="hero-row">
        <Hero
          v={`${num(h.net_lost_kbd)}`}
          u="kbd lost"
          sub={`${h.lost_pct_of_imports}% of imports`}
          tone="crit"
        />
        <Hero
          v={`$${h.brent_usd.toFixed(0)}`}
          u="Brent"
          sub={`${h.brent_delta_pct > 0 ? '+' : ''}${h.brent_delta_pct}%`}
          tone="warn"
        />
        <Hero
          v={`$${h.total_cost_usd_bn.toFixed(1)}B`}
          u="total cost"
          sub={`over ${h.duration_days} days`}
          tone="crit"
        />
      </div>

      <Stage n={1} title="Supply gap" tone="crit">
        <KV k="Baseline imports" v={`${num(gap.baseline_import_kbd)} kbd`} />
        <KV k="Gross barrels blocked" v={`${num(gap.gross_lost_kbd)} kbd`} />
        <KV k="Pipeline bypass relief" v={`−${num(gap.bypass_relief_kbd)} kbd`} good />
        <KV k="Net supply gap" v={`${num(gap.net_lost_kbd)} kbd`} strong />
        {(gap.bypass_detail as unknown as Array<Record<string, number | string>>).map(
          (b, i) => (
            <div className="micro" key={i}>
              {b.chokepoint}: India can claim {b.india_share_pct}% of{' '}
              {num(b.bypass_capacity_kbd as number)} kbd bypass →{' '}
              {num(b.relief_kbd as number)} kbd
            </div>
          ),
        )}
      </Stage>

      <Stage n={2} title="Refinery runs" tone="crit">
        <KV k="Baseline runs" v={`${num(refinery.baseline_run_kbd)} kbd`} />
        <KV k="Throughput cut" v={`${num(refinery.total_cut_kbd)} kbd`} strong />
        <KV k="Utilisation" v={`${refinery.utilisation_pct}%`} />
        <KV k="Units tripped" v={`${refinery.refineries_tripped}`} />
        <KV
          k="Delivery window"
          v={`${refinery.delivery_budget_days} days`}
        />
        <KV
          k="Compatible but too far"
          v={`${num(refinery.stranded_spare_kbd)} kbd`}
        />
        <div className="micro" style={{ marginTop: 6 }}>
          Substitute crude only counts if it can berth inside the delivery
          window. This is why distant grades cannot patch a short shock.
        </div>
        {((refinery.stranded_grades ?? []) as unknown as string[]).length > 0 && (
          <div className="stranded">
            <div className="stranded-label">
              grade-compatible, for sale, too far away
            </div>
            <div className="stranded-list">
              {((refinery.stranded_grades ?? []) as unknown as string[]).map((s) => (
                <span className="stranded-chip" key={s}>
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}
        {(refinery.by_refinery as unknown as Array<Record<string, never>>)
          .slice(0, 5)
          .map((r) => (
            <div className="ref-row" key={r.refinery_id}>
              <div className="ref-top">
                <span>{r.refinery}</span>
                <span
                  className="ref-util"
                  style={{
                    color:
                      (r.utilisation_pct as number) < 70
                        ? 'var(--crit)'
                        : (r.utilisation_pct as number) < 95
                          ? 'var(--warn)'
                          : 'var(--ok)',
                  }}
                >
                  {r.utilisation_pct}%
                </span>
              </div>
              <div className="ref-bind">{r.binding}</div>
            </div>
          ))}
      </Stage>

      <Stage n={3} title="Price" tone="warn">
        <KV k="World supply lost" v={`${price.world_supply_loss_pct}%`} />
        <KV k="Physical price move" v={`+${price.physical_price_pct}%`} />
        <KV k="Risk premium" v={`+$${price.risk_premium_usd}/bbl`} />
        <KV k="Brent" v={`$${price.brent_usd}`} strong />
        <KV k="Pump price" v={`+${price.pump_price_delta_pct}%`} />
        <div className="micro">
          Pass-through of {(result.assumptions.price_passthrough * 100).toFixed(0)}%
          — India absorbs much of a spike through excise and OMC margins.
        </div>
      </Stage>

      <Stage n={4} title="Sector stress" tone="warn">
        <KV k="Product shortfall" v={`${num(sector.product_short_kbd)} kbd`} />
        <KV k="Demand destroyed" v={`−${num(sector.demand_destroyed_kbd)} kbd`} good />
        <KV k="Unserved demand" v={`${sector.unserved_pct_of_demand}%`} strong />
        <KV k="Diesel short" v={`${sector.diesel_short_pct}%`} />
        {(sector.sectors as unknown as Array<{ sector: string; stress_pct: number }>).map(
          (s) => (
            <div className="sector-row" key={s.sector}>
              <span className="sector-name">{s.sector}</span>
              <div className="sector-bar">
                <div
                  className="sector-fill"
                  style={{
                    width: `${Math.min(100, s.stress_pct)}%`,
                    background:
                      s.stress_pct > 60
                        ? 'var(--crit)'
                        : s.stress_pct > 25
                          ? 'var(--warn)'
                          : 'var(--ok)',
                  }}
                />
              </div>
              <span className="sector-val">{s.stress_pct}%</span>
            </div>
          ),
        )}
      </Stage>

      <Stage n={5} title="Macro impact" tone="crit">
        <KV k="Price channel" v={`${macro.price_channel_gdp_pct}% GDP`} />
        <KV k="Shortage channel" v={`${macro.shortage_channel_gdp_pct}% GDP`} />
        <KV k="GDP loss" v={`$${macro.gdp_loss_usd_bn}B`} strong />
        <KV
          k="Extra import bill"
          v={`$${macro.extra_import_bill_usd_bn}B`}
        />
        <KV
          k="Total"
          v={`₹${num(
            ((macro.gdp_loss_usd_bn as number) +
              (macro.extra_import_bill_usd_bn as number)) *
              1000 *
              8.65,
          )} cr`}
          strong
        />
      </Stage>

      <div className={`spr-verdict ${h.spr_exhausted ? 'bad' : 'ok'}`}>
        <strong>Strategic reserve:</strong> at this gap the SPR covers{' '}
        {h.spr_days_at_this_gap} days against a {h.duration_days}-day shock —{' '}
        {h.spr_exhausted ? 'exhausted before the shock ends.' : 'sufficient, if drawn down in a coordinated way.'}
      </div>
    </>
  )
}

function Hero({ v, u, sub, tone }: { v: string; u: string; sub: string; tone: string }) {
  return (
    <div className="hero">
      <div className={`hero-v ${tone}`}>{v}</div>
      <div className="hero-u">{u}</div>
      <div className="hero-sub">{sub}</div>
    </div>
  )
}

function Stage({
  n,
  title,
  tone,
  children,
}: {
  n: number
  title: string
  tone: string
  children: React.ReactNode
}) {
  return (
    <div className="stage-block">
      <div className="stage-head">
        <span className={`stage-n ${tone}`}>{n}</span>
        <span className="stage-title">{title}</span>
      </div>
      <div className="stage-body">{children}</div>
    </div>
  )
}

function KV({
  k,
  v,
  strong,
  good,
}: {
  k: string
  v: string
  strong?: boolean
  good?: boolean
}) {
  return (
    <div className="kv">
      <span className="kv-k">{k}</span>
      <span
        className="kv-v"
        style={{
          color: good ? 'var(--ok)' : undefined,
          fontWeight: strong ? 700 : 400,
        }}
      >
        {v}
      </span>
    </div>
  )
}
