from pycatchmod import (SoilMoistureDeficitStore, LinearStore, NonLinearStore,
    SubCatchment, Catchment, run_catchmod)
from pycatchmod.io.json import catchment_from_json
import numpy as np
import pytest
import os
import pandas


def test_smd_store():
    """ Test the basic behaviour of the SoilMoistureDeficitStore
    """
    n = 1
    initial_upper_store = np.zeros(n)
    initial_lower_store = np.zeros(n)
    area = 1.0
    SMD = SoilMoistureDeficitStore(initial_upper_store, initial_lower_store, direct_percolation=0.2,
                                   potential_drying_constant=100, gradient_drying_curve=0.3)

    assert SMD.direct_percolation == 0.2
    assert SMD.potential_drying_constant == 100.0
    assert SMD.gradient_drying_curve == 0.3

    rainfall = np.array([10.0])
    pet = np.array([2.0])
    percolation = np.empty_like(rainfall)

    SMD.step(rainfall, pet, percolation)

    # There is currently no deficit so all effective rainfall is runoff
    np.testing.assert_allclose(percolation, rainfall-pet)
    np.testing.assert_allclose(np.array(SMD.upper_deficit), [0.0])
    np.testing.assert_allclose(np.array(SMD.lower_deficit), [0.0])


def test_linear_store():
    """ Test the behaviour of the LinearStore

    LinearStore should emulate a storage volume with the outflow proportional to the current volume,
        \frac{dV(t)}{dt} = I(t) - \frac{V(t)}{C_r}

    This test compares the performance of the analytical solutions in LinearStore (from Wilby 1994) with a numerical
    integration of the above equation.
    """
    from scipy.integrate import odeint

    def dVdt(V, t, I, Cr):
        """ RHS of LinearStore ODE """
        return I - V/Cr

    C = 0.5
    store = LinearStore(np.ones(1), linear_storage_constant=C)
    I = np.array([10.0])
    O = np.empty_like(I)
    store.step(I, O)
    # Solve system numerical for the first time-step. We use 1000 timesteps in the numerical integration
    # to test against the analytical mean value for the timestep.
    t = np.linspace(0, 1.0, 1000)
    V = odeint(dVdt, 1.0*C, t, args=(I, C))
    # Test mean outflow
    np.testing.assert_allclose(V.mean()/C, O, rtol=1e-3)
    # and end of time-step outflow.
    np.testing.assert_allclose(V[-1]/C, np.array(store.previous_outflow))

    # And repeat for a second step ...
    store.step(I, O)
    V = odeint(dVdt, V[-1], t+1.0, args=(I, C))
    # Test mean outflow
    np.testing.assert_allclose(V.mean()/C, O, rtol=1e-3)
    # and end of time-step outflow.
    np.testing.assert_allclose(V[-1]/C, np.array(store.previous_outflow))


def test_nonlinear_store():
    """ Test the behaviour of the NonLinearStore

    NonLinearStore should emulate a storage volume with the outflow proportional to the square of the current volume,
        \frac{dV(t)}{dt} = I(t) = \frac{V(t)^2}{C_q}

    This test compares the performance of the analytical soltuions in NonLinearStore (from Wilby 1994) with a numerical
    integration of the above equation.
    """
    from scipy.integrate import odeint

    def dVdt(V, t, I, Cq):
        """ RHS of NonLinearStore ODE """
        Q = I - V**2/Cq
        if V <= 0.0:
            # Volume should not be allowed to go negative. Therefore no net outflow when V <= 0.0
            return max(Q, 0.0)
        return Q

    C = 0.5
    store = NonLinearStore(np.zeros(1), nonlinear_storage_constant=C)
    I = np.array([10.0])
    O = np.empty_like(I)
    store.step(I, O)
    # Solve system numerical for the first time-step. Unlike the LinearStore there is no analytical solution given
    # for the mean outflow. Therefore we can use a single time-step in the numerical integration and average the result
    # to test against the analytical mean value for the timestep.
    t = np.linspace(0, 1.0, 2)
    V = odeint(dVdt, 0.0, t, args=(I, C))
    # Test mean outflow
    np.testing.assert_allclose(np.mean(V**2/C), O, rtol=1e-3)
    # and end of time-step outflow.
    np.testing.assert_allclose(V[-1]**2/C, np.array(store.previous_outflow), rtol=1e-3)

    # And repeat for a second step ...
    store.step(I, O)
    V = odeint(dVdt, V[-1], t+1.0, args=(I, C))
    # Test mean outflow
    np.testing.assert_allclose(np.mean(V**2/C), O, rtol=1e-3)
    # and end of time-step outflow.
    np.testing.assert_allclose(V[-1]**2/C, np.array(store.previous_outflow), rtol=1e-3)

    # And repeat for a third step with zero inflow
    I = np.array([0.0])
    store.step(I, O)
    V = odeint(dVdt, V[-1], t+1.0, args=(I, C))
    # Test mean outflow
    np.testing.assert_allclose(np.mean(V**2/C), O, rtol=1e-3)
    # and end of time-step outflow.
    np.testing.assert_allclose(V[-1]**2/C, np.array(store.previous_outflow), rtol=1e-3)

    # And repeat for a fourth step with -ve inflow
    I = np.array([-1.0])
    store.step(I, O)
    V = odeint(dVdt, V[-1], t+1.0, args=(I, C))
    # Test mean outflow
    np.testing.assert_allclose(np.mean(V**2/C), O, rtol=1e-3)
    # and end of time-step outflow.
    np.testing.assert_allclose(V[-1]**2/C, np.array(store.previous_outflow), rtol=1e-3, atol=1e-10)


def test_subcatchment_no_linear():
    """
    Test SubCatchment initialiser correctly catches invalid or no nonlinear_storage_constants
    """
    n = 10
    area = 100.0

    subcatchment = SubCatchment(area, np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n),
                                direct_percolation=0.2, potential_drying_constant=100, gradient_drying_curve=0.3,
                                linear_storage_constant=None, nonlinear_storage_constant=10.0)

    assert subcatchment.linear_store is None

    # Warning should be raised if a small or zero non-linear constant is given.
    with pytest.warns(UserWarning):
        subcatchment = SubCatchment(area, np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n),
                            direct_percolation=0.2, potential_drying_constant=100, gradient_drying_curve=0.3,
                            linear_storage_constant=0.0, nonlinear_storage_constant=10.0)

        assert subcatchment.linear_store is None

def test_subcatchment_no_nonlinear():
    """
    Test SubCatchment initialiser correctly catches invalid or no nonlinear_storage_constants
    """
    n = 10
    area = 100.0

    subcatchment = SubCatchment(area, np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n),
                                direct_percolation=0.2, potential_drying_constant=100, gradient_drying_curve=0.3,
                                linear_storage_constant=0.5, nonlinear_storage_constant=None)

    assert subcatchment.nonlinear_store is None

    # Warning should be raised if a small or zero non-linear constant is given.
    with pytest.warns(UserWarning):
        subcatchment = SubCatchment(area, np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n),
                            direct_percolation=0.2, potential_drying_constant=100, gradient_drying_curve=0.3,
                            linear_storage_constant=0.5, nonlinear_storage_constant=0.0)

        assert subcatchment.nonlinear_store is None


def test_subcatchment():
    """
    Test SubCatchment can step correctly

    """
    n = 10
    area = 100.0
    subcatchment = SubCatchment(area, np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n),
                                direct_percolation=0.2, potential_drying_constant=100, gradient_drying_curve=0.3,
                                linear_storage_constant=0.5, nonlinear_storage_constant=10.0)

    rainfall = np.arange(n, dtype=np.float64)
    pet = np.arange(n, dtype=np.float64)[::-1]
    percolation = np.empty_like(rainfall)
    outflow = np.empty_like(rainfall)

    subcatchment.step(rainfall, pet, percolation, outflow)
    # Calculate actual percolation of r soil store with no deficit (i.e. initial conditions used above)
    her = rainfall-pet
    perc = np.zeros_like(her)
    perc[her>0.0] = her[her>0.0]
    np.testing.assert_allclose(perc, percolation)

    # TODO test outflow
    assert np.all(np.isfinite(outflow))


def test_catchment():
    """
    Test the Catchment object steps correctly with some subcatchments
    """
    n = 10
    area = 100.0
    subcatchments =[
        SubCatchment(100.0, np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n),
                     direct_percolation=0.2, potential_drying_constant=100, gradient_drying_curve=0.3,
                     linear_storage_constant=0.5, nonlinear_storage_constant=10.0),
        SubCatchment(100.0, np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n),
                     direct_percolation=0.2, potential_drying_constant=100, gradient_drying_curve=0.3,
                     linear_storage_constant=0.5, nonlinear_storage_constant=10.0),
        SubCatchment(100.0, np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n),
                     direct_percolation=0.2, potential_drying_constant=100, gradient_drying_curve=0.3,
                     linear_storage_constant=0.5, nonlinear_storage_constant=10.0),
    ]

    catchment = Catchment(subcatchments)

    rainfall = np.arange(n, dtype=np.float64)
    pet = np.arange(n, dtype=np.float64)[::-1]
    percolation = np.empty((len(subcatchments), n))
    outflow = np.empty((len(subcatchments), n))

    catchment.step(rainfall, pet, percolation, outflow)
    # TODO test outflow
    assert np.all(np.isfinite(outflow))


@pytest.mark.parametrize("leap,total_flows", [(True, True), (True, False), (False, True), (False, False)])
def test_run_catchmod(leap, total_flows):
    """ Test the shape of output is correct if when there are leap dates/no leap days
    and for returning total flows or individual subcatchment flows
    """
    shape = [200, 4]
    catchment = catchment_from_json(os.path.join(os.path.dirname(__file__), "data", "thames.json"), n=shape[1])
    dates = pandas.date_range("1920-01-01", periods=200, freq="D")
    if leap:
        # remove input data for leap days
        num_leap = sum([1 for date in dates if (date.month == 2 and date.day == 29)])
        shape[0] -= num_leap
    rainfall = np.ones(shape)
    pet = np.zeros(shape)
    flow = run_catchmod(catchment, rainfall, pet, dates, total_flows)

    assert(flow.shape[0] == len(dates))
    if total_flows:
        assert(len(flow.shape) == 2)
        assert (flow.shape[1] == rainfall.shape[1])
    else:
        assert(len(flow.shape) == 3)
        assert (flow.shape[2] == len(catchment.subcatchments))
        assert (flow.shape[1] == rainfall.shape[1])


def test_run_catchmod_subcatchment_flows():
    """ test the subcatchment flows returned sum to the returned total flows """

    catchment = catchment_from_json(os.path.join(os.path.dirname(__file__), "data", "thames.json"), n=2)
    dates = pandas.date_range("1920-01-01", periods=200, freq="D")

    rainfall = np.random.randint(0, 20, [200, 2])
    pet = np.random.randint(0, 5, [200, 2])

    flow_total = run_catchmod(catchment, rainfall, pet, dates, output_total=True)
    flow_subcatchment = run_catchmod(catchment, rainfall, pet, dates, output_total=False)

    np.testing.assert_allclose(flow_total, flow_subcatchment.sum(axis=2))

    # test correct flow reshape in __main__
    flow_reshape = flow_subcatchment.reshape((len(dates), len(catchment.subcatchments) * 2), order='C')

    np.testing.assert_allclose(flow_reshape[:, 0], flow_subcatchment[:, 0, 0])
    np.testing.assert_allclose(flow_reshape[:, 3], flow_subcatchment[:, 1, 0])
