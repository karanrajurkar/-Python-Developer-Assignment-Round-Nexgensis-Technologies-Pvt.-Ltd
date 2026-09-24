"""
FastBox Logistics Simulator - Mystery Delivery System
=====================================================
A production-ready simulation of one day of operations for FastBox Logistics.

Features:
  1. Multi-format JSON Parsing: Supports both dict and list representations for
     warehouses and agents, and both 'warehouse' and 'warehouse_id' package keys.
  2. Euclidean Distance Calculation: Exact 2-D straight-line distance calculations.
  3. Nearest Agent Assignment: Packages assigned to the closest agent to warehouse
     with deterministic tie-breaking.
  4. Delivery Simulation: Models sequential legs (agent -> warehouse -> destination),
     tracking agent position dynamically after each drop-off.
  5. Performance & Efficiency Metrics: Computes packages delivered, total distance,
     and efficiency score (distance / packages). Identifies the best agent.
  6. Standard Report Generation: Outputs valid JSON report matching specification (report.json).
  7. Bonus Extensions:
     - Random delivery delays (traffic / handling simulation)
     - ASCII route & spatial distribution map
     - Dynamic mid-day agent joining and task re-dispatching
     - Detailed CSV export for top performer (and full fleet)
     - Route optimization (Greedy / Nearest-Neighbor TSP vs FIFO)
     - Automated test runner for all 10 test case files

Usage:
  python solution.py                              # Runs data.json with default settings
  python solution.py data.json                    # Explicit input file
  python solution.py base_case.json               # Run base case
  python solution.py --delays                     # Run with random delays enabled
  python solution.py --midday-agent               # Simulate new agent joining mid-day
  python solution.py --route-strategy greedy      # Run route optimization (nearest neighbor)
  python solution.py --run-all-tests              # Run all 10 test cases and display summary
"""

import json
import math
import random
import csv
import sys
import os
import argparse
import glob
from typing import Dict, List, Tuple, Any, Optional


# ---------------------------------------------------------------------------
# Distance Calculation
# ---------------------------------------------------------------------------
def euclidean_distance(point_a: List[float], point_b: List[float]) -> float:
    """
    Compute the Euclidean distance between two 2-D points.

    Formula: sqrt((x2 - x1)^2 + (y2 - y1)^2)
    Rounded to 2 decimal places.

    Parameters:
        point_a: [x, y] coordinates of first point
        point_b: [x, y] coordinates of second point

    Returns:
        float: Euclidean distance rounded to 2 decimal places
    """
    dx = point_a[0] - point_b[0]
    dy = point_a[1] - point_b[1]
    return round(math.sqrt(dx * dx + dy * dy), 2)


# ---------------------------------------------------------------------------
# Data Loading & Normalization
# ---------------------------------------------------------------------------
def load_data(filepath: str) -> Tuple[Dict[str, List[float]], Dict[str, List[float]], List[Dict[str, Any]]]:
    """
    Read and parse the JSON input file, normalizing all data formats.

    Supports:
      - Warehouses as dict: {"W1": [x, y], ...}
      - Warehouses as list: [{"id": "W1", "location": [x, y]}, ...]
      - Agents as dict:     {"A1": [x, y], ...}
      - Agents as list:     [{"id": "A1", "location": [x, y]}, ...]
      - Packages key:       'warehouse' or 'warehouse_id'

    Returns:
        tuple: (warehouses_dict, agents_dict, packages_list)
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Input file '{filepath}' does not exist.")

    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 1. Normalize warehouses
    raw_wh = raw.get("warehouses", {})
    if isinstance(raw_wh, dict):
        warehouses = {k: list(v) for k, v in raw_wh.items()}
    elif isinstance(raw_wh, list):
        warehouses = {w["id"]: list(w["location"]) for w in raw_wh}
    else:
        raise ValueError("Invalid format for 'warehouses' in JSON input.")

    # 2. Normalize agents
    raw_ag = raw.get("agents", {})
    if isinstance(raw_ag, dict):
        agents = {k: list(v) for k, v in raw_ag.items()}
    elif isinstance(raw_ag, list):
        agents = {a["id"]: list(a["location"]) for a in raw_ag}
    else:
        raise ValueError("Invalid format for 'agents' in JSON input.")

    # 3. Normalize packages
    raw_pk = raw.get("packages", [])
    if not isinstance(raw_pk, list):
        raise ValueError("Invalid format for 'packages' in JSON input (expected list).")

    packages = []
    for idx, p in enumerate(raw_pk):
        pkg_id = p.get("id", f"P{idx+1}")
        wh_key = p.get("warehouse") or p.get("warehouse_id")
        if not wh_key or wh_key not in warehouses:
            raise ValueError(f"Package '{pkg_id}' references unknown warehouse '{wh_key}'.")
        dest = p.get("destination")
        if not dest or len(dest) != 2:
            raise ValueError(f"Package '{pkg_id}' has invalid destination: {dest}")

        packages.append({
            "id": str(pkg_id),
            "warehouse": str(wh_key),
            "destination": [float(dest[0]), float(dest[1])]
        })

    return warehouses, agents, packages


# ---------------------------------------------------------------------------
# Package Assignment Logic
# ---------------------------------------------------------------------------
def assign_packages(
    warehouses: Dict[str, List[float]],
    agents: Dict[str, List[float]],
    packages: List[Dict[str, Any]],
    tie_breaker: str = "id"
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Assign each package to the nearest agent based on Euclidean distance
    from the agent's initial location to the package's warehouse.

    Tie-breaking assumption:
      If two agents have identical distances to a warehouse, ties are broken
      deterministically by alphabetical agent ID (e.g., 'A1' precedes 'A2').

    Parameters:
        warehouses: Mapping of warehouse_id -> [x, y]
        agents: Mapping of agent_id -> [x, y]
        packages: List of package dicts
        tie_breaker: Strategy for ties ('id' for alphabetical)

    Returns:
        dict: Mapping of agent_id -> list of assigned package dicts
    """
    assignment = {agent_id: [] for agent_id in agents}

    if not agents:
        return assignment

    for pkg in packages:
        wh_loc = warehouses[pkg["warehouse"]]

        # Find closest agent to this warehouse
        best_agent = None
        min_dist = float("inf")

        # Sort agents by id to guarantee deterministic tie-breaking
        for agent_id in sorted(agents.keys()):
            agent_loc = agents[agent_id]
            dist = euclidean_distance(agent_loc, wh_loc)
            if dist < min_dist:
                min_dist = dist
                best_agent = agent_id

        if best_agent is not None:
            assignment[best_agent].append(pkg)

    return assignment


# ---------------------------------------------------------------------------
# Simulation Engine
# ---------------------------------------------------------------------------
def simulate_deliveries(
    warehouses: Dict[str, List[float]],
    agents: Dict[str, List[float]],
    assignment: Dict[str, List[Dict[str, Any]]],
    use_delays: bool = False,
    routing_strategy: str = "fifo",
    delay_range: Tuple[float, float] = (0.5, 3.0),
    random_seed: Optional[int] = 42
) -> Dict[str, Any]:
    """
    Simulate the physical deliveries for all agents.

    Operational Assumptions:
      - An agent starts at their initial assigned location.
      - Each package delivery consists of two legs:
          Leg 1: agent's current position -> package's warehouse
          Leg 2: package's warehouse -> package's destination
      - After completing a delivery, the agent remains at the destination
        until dispatching to the next pickup.
      - Routing strategy:
          'fifo'    : packages delivered in the order they were assigned / appear in input.
          'greedy'  : agent chooses next nearest warehouse pickup from current location.

    Parameters:
        warehouses: Warehouse coordinates
        agents: Agent starting coordinates
        assignment: Agent -> packages mapping
        use_delays: If True, adds realistic random delays (extra simulated distance)
        routing_strategy: 'fifo' or 'greedy'
        delay_range: (min_delay, max_delay) extra distance units
        random_seed: Optional seed for reproducible delay simulation

    Returns:
        dict: Detailed results per agent including total_distance, efficiency, and delivery logs.
    """
    if random_seed is not None and use_delays:
        random.seed(random_seed)

    results = {}

    for agent_id, pkgs in assignment.items():
        current_pos = list(agents[agent_id])
        total_distance = 0.0
        delivery_log = []

        # Order packages according to routing strategy
        if routing_strategy == "greedy" and len(pkgs) > 1:
            # Nearest neighbor route from current position
            remaining = list(pkgs)
            ordered_pkgs = []
            probe_pos = list(current_pos)
            while remaining:
                # Find package whose warehouse is closest to probe_pos
                nearest_idx = min(
                    range(len(remaining)),
                    key=lambda i: euclidean_distance(probe_pos, warehouses[remaining[i]["warehouse"]])
                )
                chosen = remaining.pop(nearest_idx)
                ordered_pkgs.append(chosen)
                probe_pos = list(chosen["destination"])
        else:
            ordered_pkgs = list(pkgs)

        for pkg in ordered_pkgs:
            wh_loc = warehouses[pkg["warehouse"]]
            dest_loc = pkg["destination"]

            # Leg 1: Travel from current location to warehouse
            leg1 = euclidean_distance(current_pos, wh_loc)

            # Leg 2: Travel from warehouse to package destination
            leg2 = euclidean_distance(wh_loc, dest_loc)

            # Optional delay simulation (e.g., congestion, detours, customs)
            delay = 0.0
            if use_delays:
                delay = round(random.uniform(delay_range[0], delay_range[1]), 2)

            trip_total = round(leg1 + leg2 + delay, 2)
            total_distance += trip_total

            delivery_log.append({
                "package_id": pkg["id"],
                "warehouse": pkg["warehouse"],
                "origin": current_pos,
                "warehouse_loc": wh_loc,
                "destination": dest_loc,
                "leg1_pickup": leg1,
                "leg2_deliver": leg2,
                "delay": delay,
                "trip_total": trip_total
            })

            # Agent position updates to destination
            current_pos = list(dest_loc)

        total_distance = round(total_distance, 2)
        packages_delivered = len(ordered_pkgs)

        # Efficiency = total_distance / packages_delivered (lower is better)
        if packages_delivered > 0:
            efficiency = round(total_distance / packages_delivered, 2)
        else:
            efficiency = 0.0

        results[agent_id] = {
            "packages_delivered": packages_delivered,
            "total_distance": total_distance,
            "efficiency": efficiency,
            "final_position": current_pos,
            "deliveries": delivery_log
        }

    return results


# ---------------------------------------------------------------------------
# Bonus Feature: Dynamic Mid-Day Agent Joining
# ---------------------------------------------------------------------------
def simulate_with_midday_agent(
    warehouses: Dict[str, List[float]],
    initial_agents: Dict[str, List[float]],
    packages: List[Dict[str, Any]],
    new_agent_id: str = "A_NEW",
    new_agent_loc: Optional[List[float]] = None,
    midday_split_ratio: float = 0.5,
    use_delays: bool = False
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Bonus: Simulates a new delivery agent joining mid-day.

    Workflow:
      1. Initial packages are assigned to starting agents.
      2. The morning shift executes up to `midday_split_ratio` of total packages.
      3. At mid-day, `new_agent_id` arrives at `new_agent_loc`.
      4. All remaining pending packages are dynamically re-assigned among all
         currently available agents (including the new agent) based on their
         current real-time coordinates.
      5. The afternoon shift completes remaining deliveries.

    Returns:
        tuple: (combined_results, mid_day_metadata)
    """
    if new_agent_loc is None:
        # Default to geometric center of warehouses
        all_wh = list(warehouses.values())
        avg_x = sum(w[0] for w in all_wh) / len(all_wh)
        avg_y = sum(w[1] for w in all_wh) / len(all_wh)
        new_agent_loc = [round(avg_x, 1), round(avg_y, 1)]

    # Initial morning assignment
    morning_assignment = assign_packages(warehouses, initial_agents, packages)

    # Determine cutoff
    split_index = max(1, int(len(packages) * midday_split_ratio))
    morning_pkgs = []
    afternoon_pkgs = []

    # Flatten package execution queue in initial assigned order
    all_assigned = []
    for aid, pkgs in morning_assignment.items():
        for p in pkgs:
            all_assigned.append((aid, p))

    morning_items = all_assigned[:split_index]
    afternoon_items = [p for _, p in all_assigned[split_index:]]

    # Run morning simulation
    morning_agent_pkgs = {aid: [] for aid in initial_agents}
    for aid, p in morning_items:
        morning_agent_pkgs[aid].append(p)

    morning_results = simulate_deliveries(
        warehouses, initial_agents, morning_agent_pkgs, use_delays=use_delays
    )

    # Record agent locations at midday
    midday_agents = {}
    for aid, data in morning_results.items():
        midday_agents[aid] = data["final_position"]
    # Introduce new agent
    midday_agents[new_agent_id] = list(new_agent_loc)

    # Afternoon re-assignment of pending packages based on mid-day positions
    afternoon_assignment = assign_packages(warehouses, midday_agents, afternoon_items)

    # Run afternoon simulation starting from mid-day locations
    afternoon_results = simulate_deliveries(
        warehouses, midday_agents, afternoon_assignment, use_delays=use_delays
    )

    # Merge results
    combined_results = {}
    all_agent_ids = sorted(set(initial_agents.keys()) | {new_agent_id})

    for aid in all_agent_ids:
        m_data = morning_results.get(aid, {"packages_delivered": 0, "total_distance": 0.0, "deliveries": []})
        a_data = afternoon_results.get(aid, {"packages_delivered": 0, "total_distance": 0.0, "deliveries": []})

        total_pkgs = m_data["packages_delivered"] + a_data["packages_delivered"]
        total_dist = round(m_data["total_distance"] + a_data["total_distance"], 2)
        eff = round(total_dist / total_pkgs, 2) if total_pkgs > 0 else 0.0

        combined_results[aid] = {
            "packages_delivered": total_pkgs,
            "total_distance": total_dist,
            "efficiency": eff,
            "final_position": a_data.get("final_position", m_data.get("final_position", initial_agents.get(aid, [0, 0]))),
            "deliveries": m_data["deliveries"] + a_data["deliveries"]
        }

    metadata = {
        "new_agent_id": new_agent_id,
        "new_agent_location": new_agent_loc,
        "morning_packages_delivered": len(morning_items),
        "afternoon_packages_reassigned": len(afternoon_items)
    }

    return combined_results, metadata


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------
def generate_report(
    results: Dict[str, Any],
    output_path: str = "report.json",
    secondary_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate summary report in the required JSON schema and persist to disk.

    Report Schema:
      {
        "A1": {"packages_delivered": int, "total_distance": float, "efficiency": float},
        "A2": {"packages_delivered": int, "total_distance": float, "efficiency": float},
        ...
        "best_agent": str or null
      }

    Best Agent Selection:
      The agent with the lowest efficiency score (distance per package) among
      agents that delivered at least 1 package. Ties broken by most packages,
      then alphabetical agent ID.

    Parameters:
        results: Detailed simulation results
        output_path: Primary destination (default: 'report.json')
        secondary_path: Optional secondary destination (e.g. 'report_<name>.json')

    Returns:
        dict: The final report object
    """
    report = {}

    for agent_id in sorted(results.keys()):
        data = results[agent_id]
        report[agent_id] = {
            "packages_delivered": data["packages_delivered"],
            "total_distance": data["total_distance"],
            "efficiency": data["efficiency"]
        }

    # Find best agent
    active_agents = [
        (aid, data["efficiency"], data["packages_delivered"])
        for aid, data in results.items()
        if data["packages_delivered"] > 0
    ]

    if active_agents:
        # Sort by efficiency ascending (lower is better), then packages descending, then agent_id ascending
        active_agents.sort(key=lambda item: (item[1], -item[2], item[0]))
        best_agent = active_agents[0][0]
    else:
        best_agent = None

    report["best_agent"] = best_agent

    # Save to primary file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Save to secondary file if specified
    if secondary_path and secondary_path != output_path:
        with open(secondary_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    return report


# ---------------------------------------------------------------------------
# Bonus: ASCII Route & Spatial Visualization
# ---------------------------------------------------------------------------
def ascii_visualise(
    warehouses: Dict[str, List[float]],
    agents: Dict[str, List[float]],
    assignment: Dict[str, List[Dict[str, Any]]],
    grid_size: int = 22
) -> None:
    """
    Print an ASCII spatial visualization of warehouses, agent starting
    locations, and delivery destinations on a scaled 2-D coordinate plane.

    Legend:
      W = Warehouse
      A = Agent starting position
      * = Delivery Destination
      + = Coincident Warehouse & Agent / Destination
      . = Empty grid coordinate
    """
    coords_x = [loc[0] for loc in warehouses.values()] + [loc[0] for loc in agents.values()]
    coords_y = [loc[1] for loc in warehouses.values()] + [loc[1] for loc in agents.values()]

    for pkgs in assignment.values():
        for p in pkgs:
            coords_x.append(p["destination"][0])
            coords_y.append(p["destination"][1])

    if not coords_x:
        print("[ASCII Map]: No coordinate data available.")
        return

    min_x, max_x = min(coords_x), max(coords_x)
    min_y, max_y = min(coords_y), max(coords_y)

    span_x = max(1e-5, max_x - min_x)
    span_y = max(1e-5, max_y - min_y)

    def map_coord(point):
        gx = int((point[0] - min_x) / span_x * (grid_size - 1))
        gy = int((point[1] - min_y) / span_y * (grid_size - 1))
        return max(0, min(grid_size - 1, gx)), max(0, min(grid_size - 1, gy))

    grid = [["." for _ in range(grid_size)] for _ in range(grid_size)]

    # Mark destinations
    for pkgs in assignment.values():
        for p in pkgs:
            gx, gy = map_coord(p["destination"])
            grid[grid_size - 1 - gy][gx] = "*"

    # Mark agents
    for aid, loc in agents.items():
        gx, gy = map_coord(loc)
        curr = grid[grid_size - 1 - gy][gx]
        grid[grid_size - 1 - gy][gx] = "A" if curr == "." else "+"

    # Mark warehouses
    for wid, loc in warehouses.items():
        gx, gy = map_coord(loc)
        curr = grid[grid_size - 1 - gy][gx]
        grid[grid_size - 1 - gy][gx] = "W" if curr in (".", "*") else "+"

    print("\n" + "=" * 52)
    print("  FASTBOX LOGISTICS - 2-D SPATIAL ROUTE MAP")
    print("=" * 52)
    print("  Legend: [W]=Warehouse  [A]=Agent  [*]=Destination  [+]=Overlap")
    print("  Span: X in [{:.1f}, {:.1f}], Y in [{:.1f}, {:.1f}]".format(min_x, max_x, min_y, max_y))
    print("  " + "-" * (grid_size * 2 + 1))
    for row in grid:
        print("  |" + " ".join(row) + "|")
    print("  " + "-" * (grid_size * 2 + 1) + "\n")


# ---------------------------------------------------------------------------
# Bonus: CSV Export of Performer Delivery Logs
# ---------------------------------------------------------------------------
def export_top_to_csv(
    report: Dict[str, Any],
    results: Dict[str, Any],
    output_path: str = "top_performer.csv",
    export_all: bool = False
) -> None:
    """
    Export detailed trip logs to CSV format.

    If export_all is False, exports trips for report['best_agent'].
    If export_all is True, exports trips for all agents.
    """
    best = report.get("best_agent")
    target_agents = list(results.keys()) if export_all else ([best] if best else [])

    if not target_agents:
        print("[CSV Export]: No active agents found to export.")
        return

    fieldnames = [
        "agent_id", "package_id", "warehouse",
        "origin_x", "origin_y",
        "warehouse_x", "warehouse_y",
        "destination_x", "destination_y",
        "leg1_pickup_dist", "leg2_deliver_dist",
        "delay_dist", "trip_total_dist"
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for aid in target_agents:
            for item in results[aid]["deliveries"]:
                writer.writerow({
                    "agent_id": aid,
                    "package_id": item["package_id"],
                    "warehouse": item["warehouse"],
                    "origin_x": item["origin"][0],
                    "origin_y": item["origin"][1],
                    "warehouse_x": item["warehouse_loc"][0],
                    "warehouse_y": item["warehouse_loc"][1],
                    "destination_x": item["destination"][0],
                    "destination_y": item["destination"][1],
                    "leg1_pickup_dist": item["leg1_pickup"],
                    "leg2_deliver_dist": item["leg2_deliver"],
                    "delay_dist": item["delay"],
                    "trip_total_dist": item["trip_total"]
                })

    target_label = "All agents" if export_all else f"Top performer ({best})"
    print(f"Exported delivery logs for {target_label} to '{output_path}'.")


# ---------------------------------------------------------------------------
# CLI Argument Parser & Batch Test Runner
# ---------------------------------------------------------------------------
def run_batch_tests(test_dir: str = "Python Assignment(Delivery System Test Cases)") -> bool:
    """
    Run simulation on all JSON test files in the specified directory
    and verify correctness.
    """
    test_files = sorted(glob.glob(os.path.join(test_dir, "*.json")))
    if not test_files:
        print(f"No test files found in '{test_dir}'.")
        return False

    print("\n" + "=" * 80)
    print(f"  RUNNING BATCH VERIFICATION ON {len(test_files)} TEST CASES")
    print("=" * 80)
    print(f"{'Test Case':<32} | {'Pkgs':<6} | {'Agents':<8} | {'Best':<6} | {'Best Eff':<10} | {'Status':<6}")
    print("-" * 80)

    all_passed = True
    for tf in test_files:
        fname = os.path.basename(tf)
        try:
            wh, ag, pk = load_data(tf)
            assignment = assign_packages(wh, ag, pk)
            res = simulate_deliveries(wh, ag, assignment)
            rep = generate_report(res, output_path=f"report_{os.path.splitext(fname)[0]}.json")

            delivered_count = sum(d["packages_delivered"] for k, d in rep.items() if k != "best_agent")
            total_pkgs = len(pk)
            status = "PASS" if delivered_count == total_pkgs else "FAIL"

            best_eff = rep[rep["best_agent"]]["efficiency"] if rep["best_agent"] else 0.0
            print(f"{fname:<32} | {total_pkgs:<6} | {len(ag):<8} | {str(rep['best_agent']):<6} | {best_eff:<10.2f} | {status:<6}")

            if status != "PASS":
                all_passed = False
        except Exception as e:
            print(f"{fname:<32} | ERROR: {e}")
            all_passed = False

    print("=" * 80)
    print(f"Batch test result: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}\n")
    return all_passed


def main():
    parser = argparse.ArgumentParser(
        description="FastBox Logistics Delivery Simulator - Mystery Delivery System",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input_file", nargs="?", default="data.json",
                        help="Path to input JSON file (default: data.json)")
    parser.add_argument("--delays", action="store_true",
                        help="Simulate random delivery delays / traffic conditions")
    parser.add_argument("--route-strategy", choices=["fifo", "greedy"], default="fifo",
                        help="Routing dispatch strategy: 'fifo' (default) or 'greedy' (nearest-neighbor)")
    parser.add_argument("--midday-agent", action="store_true",
                        help="Simulate bonus feature: new agent joining mid-day")
    parser.add_argument("--midday-agent-id", default="A_MID",
                        help="ID of new agent joining mid-day (default: A_MID)")
    parser.add_argument("--midday-agent-loc", type=float, nargs=2, default=None,
                        help="[X Y] starting coordinates of mid-day agent")
    parser.add_argument("--output", default="report.json",
                        help="Output report JSON file path (default: report.json)")
    parser.add_argument("--csv", default=None,
                        help="CSV file to export detailed trip logs (default: top_performer_<input>.csv)")
    parser.add_argument("--export-all-csv", action="store_true",
                        help="Export trips for all agents to CSV, not just top performer")
    parser.add_argument("--no-ascii", action="store_true",
                        help="Suppress ASCII route visualization")
    parser.add_argument("--run-all-tests", action="store_true",
                        help="Run verification on all 10 test case files")

    args = parser.parse_args()

    if args.run_all_tests:
        run_batch_tests()
        return

    # Check input file
    input_file = args.input_file
    if not os.path.isfile(input_file):
        # Fall back to base_case.json if data.json is missing
        if input_file == "data.json" and os.path.isfile("base_case.json"):
            input_file = "base_case.json"
        else:
            print(f"ERROR: Input file '{input_file}' not found.")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("  FASTBOX LOGISTICS SIMULATOR")
    print(f"  Input Source: {input_file}")
    print(f"  Strategy    : {args.route_strategy.upper()}")
    print(f"  Delays      : {'Enabled' if args.delays else 'Disabled'}")
    print(f"  Mid-Day Agent: {'Simulated' if args.midday_agent else 'Disabled'}")
    print("=" * 60 + "\n")

    # Step 1: Load and parse data
    warehouses, agents, packages = load_data(input_file)
    print(f"Warehouses : {list(warehouses.keys())}")
    print(f"Agents     : {list(agents.keys())}")
    print(f"Packages   : {len(packages)} packages to deliver\n")

    # Step 2 & 3: Assignment & Simulation
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    secondary_report = f"report_{base_name}.json"

    if args.midday_agent:
        results, meta = simulate_with_midday_agent(
            warehouses, agents, packages,
            new_agent_id=args.midday_agent_id,
            new_agent_loc=args.midday_agent_loc,
            use_delays=args.delays
        )
        print(f"[Mid-Day Dispatch]: New agent '{meta['new_agent_id']}' joined at {meta['new_agent_location']}.")
        print(f"  - Morning completed: {meta['morning_packages_delivered']} packages.")
        print(f"  - Afternoon re-assigned: {meta['afternoon_packages_reassigned']} packages.\n")
        assignment = {aid: [item for item in res["deliveries"]] for aid, res in results.items()}
    else:
        assignment = assign_packages(warehouses, agents, packages)
        print("Initial Package Assignment (Nearest agent to warehouse):")
        for aid, pkgs in assignment.items():
            pkg_ids = [p["id"] for p in pkgs]
            print(f"  {aid}: {pkg_ids if pkg_ids else '(no packages)'}")
        print()

        results = simulate_deliveries(
            warehouses, agents, assignment,
            use_delays=args.delays,
            routing_strategy=args.route_strategy
        )

    # Step 4 & 5: Generate report & save
    report = generate_report(results, output_path=args.output, secondary_path=secondary_report)

    # Print report
    print("DELIVERY SUMMARY REPORT:")
    print("-" * 52)
    for agent_id, data in report.items():
        if agent_id == "best_agent":
            continue
        print(f"  Agent {agent_id}:")
        print(f"    Packages Delivered : {data['packages_delivered']}")
        print(f"    Total Distance     : {data['total_distance']:.2f}")
        print(f"    Efficiency Score   : {data['efficiency']:.2f}")

    print("-" * 52)
    print(f"  Most Efficient Agent : {report['best_agent']}")
    print(f"\nReport successfully saved to '{args.output}' and '{secondary_report}'.")

    # Verification: total delivered == total packages
    total_delivered = sum(d["packages_delivered"] for k, d in report.items() if k != "best_agent")
    total_pkgs = len(packages)
    status = "PASS" if total_delivered == total_pkgs else "FAIL"
    print(f"\nVerification Audit: {total_delivered}/{total_pkgs} packages delivered -- [{status}]")

    # Bonus: ASCII route visualization
    if not args.no_ascii:
        ascii_visualise(warehouses, agents, assignment)

    # Bonus: CSV export
    csv_file = args.csv or f"top_performer_{base_name}.csv"
    export_top_to_csv(report, results, output_path=csv_file, export_all=args.export_all_csv)

    print("\n" + "=" * 60)
    print("  Simulation completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
