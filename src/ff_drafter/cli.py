"""`ffdraft` — sync ESPN + Sleeper data and print it for analysis.

This layer deliberately contains no trade or waiver *judgement*. It assembles a
clean, complete brief; the reasoning lives in the Claude Code slash commands
under .claude/commands/, which read the exported JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from .config import Config, ConfigError
from .enrichment import Enricher
from .espn_client import EspnClient, build_espn_client
from .models import LeagueSnapshot
from .sleeper_client import SleeperClient
from .storage import Storage

NEEDS_SYNC = ("No synced data yet in {path}. Run `ffdraft sync` first.")


@click.group()
@click.version_option(package_name="ff-drafter")
def cli() -> None:
    """Personal ESPN Fantasy Football trade and waiver assistant."""


def _config() -> Config:
    try:
        return Config.from_env()
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from None


def _load_latest(cfg: Config) -> LeagueSnapshot:
    if not Path(cfg.db_path).exists():
        raise click.ClickException(NEEDS_SYNC.format(path=cfg.db_path))
    with Storage(cfg.db_path) as store:
        snapshot = store.latest_snapshot()
    if snapshot is None:
        raise click.ClickException(NEEDS_SYNC.format(path=cfg.db_path))
    return snapshot


@cli.command()
@click.option("--free-agents", "fa_size", default=150, show_default=True,
              help="How many free agents to pull from ESPN.")
@click.option("--activity", "activity_size", default=25, show_default=True,
              help="How many recent transactions to pull.")
def sync(fa_size: int, activity_size: int) -> None:
    """Pull fresh ESPN + Sleeper data and store a new snapshot."""
    cfg = _config()

    click.echo("Fetching league from ESPN...")
    try:
        espn = build_espn_client(cfg)
        snapshot = espn.build_snapshot(free_agent_size=fa_size,
                                       activity_size=activity_size)
    except Exception as exc:
        raise click.ClickException(
            f"Could not read the league from ESPN: {exc}\n"
            "For a private league, check ESPN_S2 / ESPN_SWID in .env are "
            "current — they expire when you log out."
        ) from None

    click.echo("Fetching injury and trend data from Sleeper...")
    sleeper = SleeperClient(cache_dir=cfg.cache_dir)
    try:
        enricher = Enricher(
            sleeper.fetch_players(),
            trending_add=sleeper.fetch_trending("add"),
            trending_drop=sleeper.fetch_trending("drop"),
        )
    except Exception as exc:
        click.echo(f"  ! Sleeper unavailable ({exc}); "
                   "continuing without injury/trend data.", err=True)
        enricher = Enricher({})

    for team in snapshot.teams:
        team.roster = enricher.enrich_all(team.roster)
    snapshot.free_agents = enricher.enrich_all(snapshot.free_agents)

    with Storage(cfg.db_path) as store:
        store.write_snapshot(snapshot)
        diff = store.diff_latest()

    matched = sum(1 for t in snapshot.teams for p in t.roster if p.sleeper_id)
    rostered = sum(len(t.roster) for t in snapshot.teams)
    click.echo(
        f"\nSnapshot saved to {cfg.db_path} — week {snapshot.current_week}, "
        f"{len(snapshot.teams)} teams, {rostered} rostered players "
        f"({matched} enriched), {len(snapshot.free_agents)} free agents."
    )

    if diff.is_first_snapshot:
        click.echo("This is the first snapshot — run `ffdraft sync` again "
                   "later to see what changed.")
        return

    click.echo("\nChanges since last sync")
    click.echo("-" * 60)
    if diff.injury_changes:
        click.echo("Injury status:")
        for change in diff.injury_changes:
            where = change.team_name or "FA"
            click.echo(f"  {change.name} ({where}): "
                       f"{change.previous or 'healthy'} -> "
                       f"{change.current or 'healthy'}")
    for label, players in (("Newly available", diff.new_free_agents),
                           ("Picked up by another team", diff.rostered_away)):
        if players:
            click.echo(f"{label}:")
            for p in players[:15]:
                click.echo(f"  {p.name} ({p.position}, {p.pro_team})")
    if diff.roster_moves:
        click.echo("League transactions:")
        for move in diff.roster_moves[:15]:
            bid = f" (${move.bid_amount})" if move.bid_amount else ""
            click.echo(f"  {move.team_name}: {move.action} "
                       f"{move.player_name}{bid}")
    if not any((diff.injury_changes, diff.new_free_agents,
                diff.rostered_away, diff.roster_moves)):
        click.echo("  Nothing notable changed.")


@cli.command()
@click.option("--team", "team_name", default=None,
              help="Team to show. Defaults to your own team.")
def roster(team_name: Optional[str]) -> None:
    """Print a team's roster with injury and trend data."""
    cfg = _config()
    snapshot = _load_latest(cfg)

    if team_name:
        team = snapshot.team_by_name(team_name)
        if team is None:
            names = ", ".join(t.name for t in snapshot.teams)
            raise click.ClickException(
                f"No team named {team_name!r}. League teams are: {names}")
    else:
        team = snapshot.my_team
        if team is None:
            names = ", ".join(t.name for t in snapshot.teams)
            raise click.ClickException(
                "Your own team is not identified — set ESPN_TEAM_NAME in .env "
                f"or pass --team. League teams are: {names}")

    click.echo(f"\n{team.name}  ({team.record}, {team.points_for:.1f} PF, "
               f"standing {team.standing})")
    click.echo("=" * 78)
    for label, players in (("STARTERS", team.starters), ("BENCH", team.bench)):
        if not players:
            continue
        click.echo(f"\n{label}")
        click.echo(_player_header())
        for p in players:
            click.echo(_player_row(p))


@cli.command()
def league() -> None:
    """Print standings and every team's roster at a glance."""
    cfg = _config()
    snapshot = _load_latest(cfg)

    click.echo(f"\nWeek {snapshot.current_week} standings")
    click.echo("=" * 78)
    click.echo(f"{'#':<3} {'Team':<28} {'Rec':<8} {'PF':>8} {'PA':>8}")
    for team in sorted(snapshot.teams, key=lambda t: t.standing):
        mark = " *" if team.is_mine else "  "
        click.echo(f"{team.standing:<3} {team.name[:26]:<26}{mark} "
                   f"{team.record:<8} {team.points_for:>8.1f} "
                   f"{team.points_against:>8.1f}")

    for team in sorted(snapshot.teams, key=lambda t: t.standing):
        click.echo(f"\n{team.name} ({team.record})")
        click.echo("-" * 78)
        click.echo(_player_header())
        for p in team.starters + team.bench:
            click.echo(_player_row(p))


@cli.command()
@click.option("--path", "path", default=None, type=click.Path(),
              help="Where to write the JSON brief.")
def export(path: Optional[str]) -> None:
    """Write the latest snapshot as JSON for the analysis slash commands."""
    cfg = _config()
    snapshot = _load_latest(cfg)
    target = Path(path) if path else Path(cfg.export_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w") as fh:
        json.dump(snapshot.to_dict(), fh, indent=2)
    click.echo(f"Wrote {target}")


@cli.command()
@click.argument("player_name")
def history(player_name: str) -> None:
    """Show how one player's status has moved across syncs."""
    cfg = _config()
    if not Path(cfg.db_path).exists():
        raise click.ClickException(NEEDS_SYNC.format(path=cfg.db_path))
    with Storage(cfg.db_path) as store:
        entries = store.player_history(name=player_name)
    if not entries:
        raise click.ClickException(f"No history recorded for {player_name!r}.")
    click.echo(f"\n{player_name}")
    click.echo("=" * 78)
    click.echo(f"{'When (UTC)':<20} {'Roster':<22} {'Injury':<14} "
               f"{'Own%':>6} {'Adds':>8}")
    for e in entries:
        click.echo(f"{e.taken_at:%Y-%m-%d %H:%M}     "
                   f"{(e.team_name or 'FA')[:20]:<22} "
                   f"{(e.injury_status or '-'):<14} "
                   f"{e.percent_owned:>6.1f} "
                   f"{_maybe_int(e.trending_add_count):>8}")


def _player_header() -> str:
    return (f"{'Slot':<5} {'Pos':<4} {'Player':<26} {'Tm':<4} {'Pts':>7} "
            f"{'Proj':>7} {'Own%':>6}  Status")


def _player_row(p) -> str:
    status_bits = []
    if p.injury_status:
        body = f" ({p.injury_body_part})" if p.injury_body_part else ""
        status_bits.append(f"{p.injury_status}{body}")
    elif p.espn_injury_status and p.espn_injury_status not in ("ACTIVE", "NORMAL"):
        status_bits.append(p.espn_injury_status)
    if p.trending_add_count:
        status_bits.append(f"+{p.trending_add_count:,} adds")
    if p.trending_drop_count:
        status_bits.append(f"-{p.trending_drop_count:,} drops")
    return (f"{p.lineup_slot:<5} {p.position:<4} {p.name[:24]:<26} "
            f"{p.pro_team:<4} {p.total_points:>7.1f} "
            f"{p.projected_total_points:>7.1f} {p.percent_owned:>6.1f}  "
            + ", ".join(status_bits))


def _maybe_int(value) -> str:
    return f"{value:,}" if value else "-"


if __name__ == "__main__":  # pragma: no cover
    cli()
