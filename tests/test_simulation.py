from pathlib import Path

from simulation.sim_drones import RoomBounds, SimDrone, Simulation, make_swap_scenario
from simulation.visualize import animate_simulation, plot_static_paths


def test_drone_moves_toward_destination_over_time():
    d = SimDrone("drone_a", position=(0, 0, 1), destination=(5, 0, 1), max_speed=1.0)
    bounds = RoomBounds(x_max=5, y_max=5)
    start_dist = d.distance_to_destination()
    for _ in range(10):
        d.step(dt=0.1, bounds=bounds)
    assert d.distance_to_destination() < start_dist
    assert len(d.path_history) > 1


def test_drone_arrives_and_then_stops_moving():
    d = SimDrone("drone_a", position=(0, 0, 1), destination=(1, 0, 1), max_speed=1.0)
    bounds = RoomBounds(x_max=5, y_max=5)
    for _ in range(50):  # plenty of time to arrive
        d.step(dt=0.1, bounds=bounds)
    assert d.has_arrived()
    history_len_at_arrival = len(d.path_history)
    for _ in range(5):
        d.step(dt=0.1, bounds=bounds)  # should be a no-op now
    assert len(d.path_history) == history_len_at_arrival


def test_two_drones_swap_scenario_paths_cross():
    sim = make_swap_scenario(bounds=RoomBounds())
    steps_taken = sim.run(max_steps=5000)
    assert steps_taken > 0
    assert sim.all_arrived()

    # Both drones should have position-updated histories with multiple points
    for d in sim.drones:
        assert len(d.path_history) > 5

    # Since they start at opposite corners and swap, the minimum
    # inter-drone distance over the run must be much smaller than the
    # starting distance -> paths genuinely crossed near the middle.
    a_hist = sim.get_drone("drone_a").path_history
    b_hist = sim.get_drone("drone_b").path_history
    n = min(len(a_hist), len(b_hist))
    min_gap = min(
        ((a_hist[i][0] - b_hist[i][0]) ** 2 + (a_hist[i][1] - b_hist[i][1]) ** 2) ** 0.5
        for i in range(n)
    )
    start_gap = ((a_hist[0][0] - b_hist[0][0]) ** 2 + (a_hist[0][1] - b_hist[0][1]) ** 2) ** 0.5
    assert min_gap < start_gap * 0.2


def test_room_bounds_are_configurable_not_hardcoded():
    tiny_room = RoomBounds(x_min=0, x_max=1, y_min=0, y_max=1, z_min=0, z_max=1)
    sim = make_swap_scenario(bounds=tiny_room, max_speed=2.0, dt=0.05)
    sim.run(max_steps=2000)

    for d in sim.drones:
        for pos in d.path_history:
            assert tiny_room.contains(pos), f"{pos} escaped the configured 1x1x1 room"
            # and definitely nowhere near the *default* 5x5x3 bounds edge
            assert pos[0] <= 1.001 and pos[1] <= 1.001


def test_large_custom_room_also_respected():
    big_room = RoomBounds(x_min=-10, x_max=10, y_min=-10, y_max=10, z_min=0, z_max=8)
    sim = make_swap_scenario(bounds=big_room, max_speed=3.0)
    sim.run(max_steps=5000)
    for d in sim.drones:
        for pos in d.path_history:
            assert big_room.contains(pos)


def test_visualization_produces_animated_gif(tmp_path):
    sim = make_swap_scenario()
    out_path = tmp_path / "swap_animation.gif"
    result_path = animate_simulation(sim, out_path, fps=10)
    assert result_path.exists()
    assert result_path.stat().st_size > 1000  # not an empty/degenerate file


def test_visualization_produces_static_path_plot(tmp_path):
    sim = make_swap_scenario()
    sim.run(max_steps=5000)
    out_path = tmp_path / "paths.png"
    result_path = plot_static_paths(sim, out_path)
    assert result_path.exists()
    assert result_path.stat().st_size > 1000
