"""
TODO:
- Lets change the order of functions to match the call order from construct_tech_model
- We need to be careful with inflow and input max/mins
- Adopt documentation
"""


from pyomo.environ import *
from pyomo.gdp import *
import copy
from warnings import warn
import pandas as pd
import numpy as np
from pathlib import Path
from scipy.interpolate import griddata
import random

import src.utilities
from src.components.technologies.utilities import FittedPerformance, fit_piecewise_function
from src.components.technologies.technology import Technology
from src.components.utilities import perform_disjunct_relaxation
from ...utilities import annualize, set_discount_rate


class OceanBattery3(Technology):

    def __init__(self,
                 tec_data):
        super().__init__(tec_data)

        self.fitted_performance = FittedPerformance()
        self.save_specific_design = None
        self.bounds = {}

    def fit_technology_performance(self, node_data):
        """
        Fits ocean battery

        :param node_data: data on node
        """
        # Climate data & Number of timesteps
        climate_data = node_data.data['climate_data']
        time_steps = len(climate_data)

        # Output Bounds
        for car in self.performance_data['output_carrier']:
            self.fitted_performance.bounds['output'][car] = np.column_stack((np.zeros(shape=time_steps),
                                                             np.ones(shape=time_steps) *
                                                             self.performance_data['performance']['turbine_slots'] *
                                                             self.performance_data['performance']['turbine_power_ub']))
        # Todo: input and output bounds are defined once as flows and here as electricity in/out
        # Input Bounds
        for car in self.performance_data['input_carrier']:
            self.fitted_performance.bounds['input'][car] = np.column_stack((np.zeros(shape=time_steps),
                                                            np.ones(shape=time_steps) *
                                                            self.performance_data['performance']['pump_slots'] *
                                                            self.performance_data['performance']['pump_power_ub']))

        # Coefficients
        for par in self.performance_data['performance']:
            self.fitted_performance.coefficients[par] = self.performance_data['performance'][par]

        # Time dependent coefficients
        self.fitted_performance.time_dependent_coefficients = 1

        # parameters needed for pump and turbine performance calculations
        nominal_head = self.fitted_performance.coefficients['nominal_head']
        frequency = self.fitted_performance.coefficients['frequency']
        pole_pairs = self.fitted_performance.coefficients['pole_pairs']
        N = (120*frequency)/(pole_pairs*2)
        omega = 2*np.pi*N/60
        nr_segments =  self.fitted_performance.coefficients['nr_segments']

        # PUMPS: PRE-PROCESSING AND FITTING
        self.performance_data['pump_performance'] = {}

        # obtain performance data from file
        performance_pumps = pd.read_csv('data/technology_data/Pump_performance.csv', delimiter=";")

        # convert performance data from (omega s, eta) to (Qin, Pin)
        performance_pumps['Q_in'] = performance_pumps.apply(lambda row: ((row['Specific_rotational_speed'] *
                                                                          ((9.81 * nominal_head) ** 0.75)) / omega) ** 2,
                                                            axis=1)

        performance_pumps['P_in'] = performance_pumps.apply(lambda row: (9.81 * 1000 * nominal_head * row['Q_in']) /
                                                                        (row['Efficiency'] / 100) * 10 ** -6, axis=1)



        # group performance data per pump type
        pumps = performance_pumps.groupby('Pump_type')
        for pump in ['Axial', 'Mixed_flow', 'Radial']:
            self.performance_data['pump_performance'][pump] = pumps.get_group(pump)

            # WATCH OUT DIRTY FIX
            normalisation_factor = self.performance_data['pump_performance'][pump]['Q_in'] / self.performance_data['pump_performance'][pump]['P_in']
            self.performance_data['pump_performance'][pump]['P_in'] = self.performance_data['pump_performance'][pump]['P_in'] / max(self.performance_data['pump_performance'][pump]['P_in'])
            self.performance_data['pump_performance'][pump]['Q_in'] = self.performance_data['pump_performance'][pump]['P_in'] * normalisation_factor


        # Perform fitting
        for pump in ['Axial', 'Mixed_flow', 'Radial']:
            # parameters to be fitted
            x = self.performance_data['pump_performance'][pump]['P_in']
            y = {}
            y['Q_in'] = self.performance_data['pump_performance'][pump]['Q_in']

            # fitting data
            fit_pump = fit_piecewise_function(x, y, nr_segments)

            # Pass to dictionary
            self.performance_data['pump_performance'][pump] = fit_pump

        # TURBINES: PRE-PROCESSING AND FITTING
        self.performance_data['turbine_performance'] = {}

        # obtain performance data from file
        performance_turbines = pd.read_csv('data/technology_data/Turbine_performance.csv', delimiter=";")

        # convert performance data from (omega s, eta) to (Qout, Pout)
        performance_turbines['Q_out'] = performance_turbines.apply(lambda row: ((row['Specific_rotational_speed'] *
                                                                                 ((9.81 * nominal_head) ** 0.75)) /
                                                                                omega) ** 2, axis=1)

        performance_turbines['P_out'] = performance_turbines.apply(lambda row: 9.81 * 1000 * nominal_head *
                                                                               row['Q_out'] * row['Efficiency']
                                                                               * 10 ** -6, axis=1)

        # group performance data per turbine type
        turbines = performance_turbines.groupby('Turbine_type')
        for turbine in ['Francis', 'Kaplan', 'Pelton']:
            self.performance_data['turbine_performance'][turbine] = turbines.get_group(turbine)

            # WATCH OUT DIRTY FIX
            normalisation_factor = self.performance_data['turbine_performance'][turbine]['Q_out'] / self.performance_data['turbine_performance'][turbine]['P_out']
            self.performance_data['turbine_performance'][turbine]['P_out'] = self.performance_data['turbine_performance'][turbine]['P_out'] / max(self.performance_data['turbine_performance'][turbine]['P_out'])
            self.performance_data['turbine_performance'][turbine]['Q_out'] = self.performance_data['turbine_performance'][turbine]['P_out'] * normalisation_factor


        # Perform fitting
        for turbine in ['Francis', 'Kaplan', 'Pelton']:
            # get performance data for that turbine
            x = self.performance_data['turbine_performance'][turbine]['P_out']
            y = {}
            y['Q_out'] = self.performance_data['turbine_performance'][turbine]['Q_out']

            # fitting data
            fit_turbine = fit_piecewise_function(x, y, nr_segments)

            # Pass to dictionary
            self.performance_data['turbine_performance'][turbine] = fit_turbine

    def __calulate_bounds(self, energyhub):

        coeff = self.fitted_performance.coefficients

        self.bounds['size_min'] = self.size_min
        self.bounds['size_max'] = self.size_max
        self.bounds['pump_flow_ub'] = 10
        self.bounds['pump_power_ub'] = self.bounds['pump_flow_ub'] * 5
        self.bounds['turbine_flow_ub'] = 10
        self.bounds['turbine_power_ub'] = self.bounds['turbine_flow_ub'] * 5

        # Global parameters
        configuration = energyhub.configuration
        economics = self.economics
        discount_rate = set_discount_rate(configuration, economics)
        annualization_factor = annualize(discount_rate, economics.lifetime)
        self.bounds['capex_turbines'] = annualization_factor * coeff['capex_turbines']
        self.bounds['capex_pumps'] = annualization_factor * coeff['capex_turbines']

    def construct_tech_model(self, b_tec, energyhub):
        """
        Adds constraints to technology blocks for tec_type STOR, resembling a storage technology

        The performance
        functions are fitted in ``src.model_construction.technology_performance_fitting``.
        Note that this technology only works for one carrier, and thus the carrier index is dropped in the below notation.

        **Parameter declarations:**

        - :math:`{\\eta}_{in}`: Charging efficiency

        - :math:`{\\eta}_{out}`: Discharging efficiency

        - :math:`{\\lambda_1}`: Self-Discharging coefficient (independent of environment)

        - :math:`{\\lambda_2(\\Theta)}`: Self-Discharging coefficient (dependent on environment)

        - :math:`Input_{max}`: Maximal charging capacity in one time-slice

        - :math:`Output_{max}`: Maximal discharging capacity in one time-slice

        **Variable declarations:**

        - Storage level in :math:`t`: :math:`E_t`

        - Charging in :math:`t`: :math:`Input_{t}`

        - Discharging in :math:`t`: :math:`Output_{t}`

        **Constraint declarations:**

        - Maximal charging and discharging:

          .. math::
            Input_{t} \leq Input_{max}

          .. math::
            Output_{t} \leq Output_{max}

        - Size constraint:

          .. math::
            E_{t} \leq S

        - Storage level calculation:

          .. math::
            E_{t} = E_{t-1} * (1 - \\lambda_1) - \\lambda_2(\\Theta) * E_{t-1} + {\\eta}_{in} * Input_{t} - 1 / {\\eta}_{out} * Output_{t}

        - If ``allow_only_one_direction == 1``, then only input or output can be unequal to zero in each respective time
          step (otherwise, simultanous charging and discharging can lead to unwanted 'waste' of energy/material).

        :param obj model: instance of a pyomo model
        :param obj b_tec: technology block
        :param tec_data: technology data
        :return: technology block
        """
        super(OceanBattery3, self).construct_tech_model(b_tec, energyhub)

        self.save_specific_design = energyhub.configuration.reporting.save_path

        nr_timesteps_averaged = energyhub.model_information.averaged_data_specs.nr_timesteps_averaged

        # Global parameters
        configuration = energyhub.configuration
        economics = self.economics
        discount_rate = set_discount_rate(configuration, economics)
        annualization_factor = annualize(discount_rate, economics.lifetime)

        self.__calulate_bounds(energyhub)

        b_tec.para_unit_capex_reservoir = Param(domain=Reals, initialize=economics.capex_data['unit_capex'], mutable=True)
        b_tec.para_unit_capex_reservoir_annual = Param(domain=Reals,
                                                       initialize=annualization_factor * economics.capex_data['unit_capex'],
                                                       mutable=True)
        # Todo: do recalculation to EUR/m³ here

        # Method sections
        b_tec = self.__define_vars(b_tec)
        b_tec = self.__define_storage_level(b_tec, nr_timesteps_averaged)
        b_tec = self.__define_turbine_design(b_tec)
        b_tec = self.__define_pump_design(b_tec)
        b_tec = self.__define_turbines(b_tec, energyhub)
        b_tec = self.__define_pumps(b_tec, energyhub)

        # Aggregate Input/Output
        def init_total_input(const, t, car):
            return b_tec.var_input[t, car] == \
                   sum(b_tec.var_input_pump[t, pump] for pump in b_tec.set_pump_slots)
        b_tec.const_total_input = Constraint(self.set_t, b_tec.set_input_carriers, rule=init_total_input)

        def init_total_output(const, t, car):
            return b_tec.var_output[t, car] == \
                   sum(b_tec.var_output_turbine[t, turbine] for turbine in b_tec.set_turbine_slots)
        b_tec.const_total_output = Constraint(self.set_t, b_tec.set_output_carriers, rule=init_total_output)

        def init_total_inflow(const, t):
            return b_tec.var_total_inflow[t] == \
                   sum(b_tec.var_inflow_pump[t, pump] for pump in b_tec.set_pump_slots)
        b_tec.const_total_inflow = Constraint(self.set_t, rule=init_total_inflow)

        def init_total_outflow(const, t):
            return b_tec.var_total_outflow[t] == \
                   sum(b_tec.var_outflow_turbine[t, turbine] for turbine in b_tec.set_turbine_slots)
        b_tec.const_total_outflow = Constraint(self.set_t, rule=init_total_outflow)

        # CAPEX Calculation
        b_tec.const_capex_aux = Constraint(expr=b_tec.para_unit_capex_reservoir_annual * b_tec.var_size +
                                                sum(b_tec.var_capex_turbine[turbine] for
                                                                     turbine in b_tec.set_turbine_slots) +
                                                sum(b_tec.var_capex_pump[pump] for pump in b_tec.set_pump_slots) ==
                                                b_tec.var_capex_aux)

        return b_tec

    def __define_vars(self, b_tec):

        # Additional parameters
        coeff = self.fitted_performance.coefficients
        pump_slots = coeff['pump_slots']
        turbine_slots = coeff['turbine_slots']

        # Additional sets
        b_tec.set_pump_slots = RangeSet(pump_slots)
        b_tec.set_turbine_slots = RangeSet(turbine_slots)

        # Additional decision variables
        # Global
        b_tec.var_storage_level = Var(self.set_t_full, domain=NonNegativeReals,
                                      bounds=(self.bounds['size_min'], self.bounds['size_max']))
        b_tec.var_total_inflow = Var(self.set_t_full, domain=NonNegativeReals,
                                     bounds=(0, pump_slots * self.bounds['pump_flow_ub']))
        b_tec.var_total_outflow = Var(self.set_t_full, domain=NonNegativeReals,
                                      bounds=(0, turbine_slots * self.bounds['turbine_power_ub']))

        # Pumps
        b_tec.var_designflow_single_pump = Var(domain=NonNegativeReals, bounds=(0, self.bounds['pump_flow_ub']))
        b_tec.var_designpower_single_pump = Var(domain=NonNegativeReals, bounds=(0, self.bounds['pump_power_ub']))

        b_tec.var_capex_pump = Var(b_tec.set_pump_slots, domain=NonNegativeReals,
                                   bounds=(0, self.bounds['capex_pumps']))
        b_tec.var_input_pump = Var(self.set_t_full, b_tec.set_pump_slots, domain=NonNegativeReals,
                                   bounds=(0, self.bounds['pump_power_ub']))
        b_tec.var_inflow_pump = Var(self.set_t_full, b_tec.set_pump_slots, domain=NonNegativeReals,
                                    bounds=(0, self.bounds['pump_flow_ub']))

        # Turbines
        b_tec.var_designflow_single_turbine = Var(domain=NonNegativeReals, bounds=(0, self.bounds['turbine_flow_ub']))
        b_tec.var_designpower_single_turbine = Var(domain=NonNegativeReals, bounds=(0, self.bounds['turbine_power_ub']))

        # TODO: change the bounds!
        b_tec.var_capex_turbine = Var(b_tec.set_turbine_slots, domain=NonNegativeReals,
                                      bounds=(0, self.bounds['capex_turbines']))
        b_tec.var_output_turbine = Var(self.set_t_full, b_tec.set_turbine_slots, domain=NonNegativeReals,
                                       bounds=(0, self.bounds['turbine_power_ub']))
        b_tec.var_outflow_turbine = Var(self.set_t_full, b_tec.set_turbine_slots, domain=NonNegativeReals,
                                        bounds=(0, self.bounds['turbine_flow_ub']))

        return b_tec


    def __define_storage_level(self, b_tec, nr_timesteps_averaged):

        coeff = self.fitted_performance.coefficients

        # Additional parameters
        eta_lambda = coeff['lambda']
        min_fill = coeff['min_fill']

        # Fill constraints
        def init_fill_constraint_up(const, t):
            return b_tec.var_storage_level[t] <= b_tec.var_size
        b_tec.const_size_up = Constraint(self.set_t_full, rule=init_fill_constraint_up)

        def init_fill_constraint_low(const, t):
            return b_tec.var_storage_level[t] >= min_fill * b_tec.var_size
        b_tec.const_size_low = Constraint(self.set_t_full, rule=init_fill_constraint_low)

        # Storage level calculation
        def init_storage_level(const, t, car):
            if t == 1:  # couple first and last time interval
                return b_tec.var_storage_level[t] == \
                       b_tec.var_storage_level[max(self.set_t_full)] * (1 - eta_lambda) ** nr_timesteps_averaged + \
                       (b_tec.var_total_inflow[t] - b_tec.var_total_outflow[t]) * \
                       sum((1 - eta_lambda) ** i for i in range(0, nr_timesteps_averaged))
            else:  # all other time intervals
                return b_tec.var_storage_level[t] == \
                       b_tec.var_storage_level[t - 1] * (1 - eta_lambda) ** nr_timesteps_averaged + \
                       (b_tec.var_total_inflow[t] - b_tec.var_total_outflow[t]) * \
                       sum((1 - eta_lambda) ** i for i in range(0, nr_timesteps_averaged))

        b_tec.const_storage_level = Constraint(self.set_t_full, b_tec.set_input_carriers, rule=init_storage_level)

        return b_tec

    def __define_turbine_design(self, b_tec):
        # Turbine design (determines design flowrate and design power)
        bp_x = [0.1, 0.9, 1.2]
        alpha2 = [1.8, 2]
        alpha1 = [0, 0.1]
        s_indicators_turbine_design = range(0, len(bp_x) - 1)

        def turbine_design_dis_init(dis, ind):
            def init_design_power(const):
                return b_tec.var_designpower_single_turbine == alpha1[ind] + alpha2[
                    ind] * b_tec.var_designflow_single_turbine

            dis.const_design_power = Constraint(rule=init_design_power)

            def init_design_power_lb(const):
                return (b_tec.var_designflow_single_turbine >= bp_x[ind - 1])

            dis.const_inflow_lb = Constraint(rule=init_design_power_lb)

            def init_design_power_ub(const):
                return (b_tec.var_designflow_single_turbine <= bp_x[ind])

            dis.const_inflow_ub = Constraint(rule=init_design_power_ub)

        b_tec.dis_turbine_design = Disjunct(s_indicators_turbine_design, rule=turbine_design_dis_init)

        # Bind disjuncts
        def bind_disjunctions(dis):
            return [b_tec.dis_turbine_design[i] for i in s_indicators_turbine_design]
        b_tec.disjunction_turbine_design = Disjunction(rule=bind_disjunctions)

        return b_tec

    def __define_pump_design(self, b_tec):
        # Pump design (determines design flowrate and design power)
        bp_x = [0.1, 0.9, 1.2]
        alpha2 = [1.8, 2]
        alpha1 = [0, -0.1]
        s_indicators_pump_design = range(0, len(bp_x) - 1)

        def pump_design_dis_init(dis, ind):
            def init_design_power(const):
                return b_tec.var_designpower_single_pump == alpha1[ind] + alpha2[ind] * b_tec.var_designflow_single_pump

            dis.const_design_power = Constraint(rule=init_design_power)

            def init_design_power_lb(const):
                return (b_tec.var_designflow_single_pump >= bp_x[ind - 1])

            dis.const_inflow_lb = Constraint(rule=init_design_power_lb)

            def init_design_power_ub(const):
                return (b_tec.var_designflow_single_pump <= bp_x[ind])

            dis.const_inflow_ub = Constraint(rule=init_design_power_ub)

        b_tec.dis_pump_design = Disjunct(s_indicators_pump_design, rule=pump_design_dis_init)

        # Bind disjuncts
        def bind_disjunctions(dis):
            return [b_tec.dis_pump_design[i] for i in s_indicators_pump_design]
        b_tec.disjunction_pump_design = Disjunction(rule=bind_disjunctions)

        return b_tec

    def __define_turbines(self, b_tec, energyhub):
        """
        This function establishes all components for the turbines. Is is organized in multiple levels
        (hierarchical) with the following structure. Description in brackets is the pyomo component type.

        turbine_block, indexed by turbine slots (Block)
            In each slot there can be a different turbine type. dis_turbine_types (Disjunct)
                Each turbine type is modelled as a block: turbine_performance_block (Block)
                    Each turbine type block (turbine_performance_block) contains a disjunct for on-off scheduling
        """

        coeff = self.fitted_performance.coefficients

        configuration = energyhub.configuration
        economics = self.economics
        discount_rate = set_discount_rate(configuration, economics)
        annualization_factor = annualize(discount_rate, economics.lifetime)

        capex_turbines = {}
        capex_turbines[0] = 0
        capex_turbines[1] = annualization_factor * coeff['capex_turbines']

        # Turbine performance
        s_indicators_install = range(0, 2)

        def turbine_install_dis_init(dis, turb_slot, ind):
            """
            Disjunct deciding for each slot if installed or not
            """
            if ind == 0: # not install

            # Flow and power constraints
                def init_outflow_not_installed(const, t):
                    return b_tec.var_outflow_turbine[t, turb_slot] == 0
                dis.const_outflow_not_installed = Constraint(self.set_t_full, rule=init_outflow_not_installed)

                def init_output_not_installed(const, t):
                    return b_tec.var_output_turbine[t, turb_slot] == 0
                dis.const_output_not_installed = Constraint(self.set_t_full, rule=init_output_not_installed)

            # CAPEX constraint
                def init_turbine_not_installed_capex(const):
                    return b_tec.var_capex_turbine[turb_slot] == 0
                dis.const_turbine_not_installed_capex = Constraint(rule=init_turbine_not_installed_capex)

            elif ind == 1: # install

                # CAPEX constraint
                def init_turbine_installed_capex(const):
                    return b_tec.var_capex_turbine[turb_slot] == (capex_turbines[ind] * b_tec.var_designflow_single_turbine)
                dis.const_turbine_installed_capex = Constraint(rule=init_turbine_installed_capex)

                def turbine_performance_block_init(b_turbine_performance):

                    beta1 = [2.3]
                    beta2 = [0]
                    bp_x = [0.1, 1]

                    s_indicators_onoff = range(0, len(bp_x))

                    def turbine_onoff_dis_init(dis, t, ind):
                        if ind == 0: # off
                            def init_outflow_off(const):
                                return b_tec.var_outflow_turbine[t, turb_slot] == 0
                            dis.const_outflow_off = Constraint(rule=init_outflow_off)

                            def init_output_off(const):
                                return b_tec.var_output_turbine[t, turb_slot] == 0
                            dis.const_output_off = Constraint(rule=init_output_off)

                        else: # on
                            def init_outflow_lb(const):
                                return (b_tec.var_outflow_turbine[t, turb_slot] >= bp_x[ind - 1] *
                                        b_tec.var_designflow_single_turbine)
                            dis.const_outflow_lb = Constraint(rule=init_outflow_lb)

                            def init_outflow_ub(const):
                                return (b_tec.var_outflow_turbine[t, turb_slot] <= bp_x[ind] *
                                        b_tec.var_designflow_single_turbine)
                            dis.const_outflow_ub = Constraint(rule=init_outflow_ub)

                            def init_output_on(const):
                                return (b_tec.var_output_turbine[t, turb_slot] ==
                                        beta1[ind - 1] * b_tec.var_designpower_single_turbine +
                                        beta2[ind - 1] * b_tec.var_outflow_turbine[t, turb_slot])
                            dis.const_output_on = Constraint(rule=init_output_on)

                        return dis

                    b_turbine_performance.dis_turbine_onoff = Disjunct(self.set_t_full, s_indicators_onoff,
                                                                       rule=turbine_onoff_dis_init)

                    def bind_disjunctions_turbine_onoff(dis, t):
                        return [b_turbine_performance.dis_turbine_onoff[t, i] for i in s_indicators_onoff]
                    b_turbine_performance.disjunction_turbine_onoff = Disjunction(self.set_t_full,
                                                                                  rule=bind_disjunctions_turbine_onoff)

                    b_turbine_performance = perform_disjunct_relaxation(b_turbine_performance, method='gdp.hull')

                    return b_turbine_performance

                dis.turbine_performance_block = Block(rule=turbine_performance_block_init)

            return dis

        b_tec.dis_turbine_install = Disjunct(b_tec.set_turbine_slots, s_indicators_install,
                                                 rule=turbine_install_dis_init)

        def bind_disjunctions_turbine_install(dis, turb_slot):
            return [b_tec.dis_turbine_install[turb_slot, i] for i in s_indicators_install]
        b_tec.disjunction_turbine_install = Disjunction(b_tec.set_turbine_slots,
                                                                rule=bind_disjunctions_turbine_install)
        b_tec = perform_disjunct_relaxation(b_tec, method='gdp.hull')

        return b_tec

    def __define_pumps(self, b_tec, energyhub):
        """
        This function establishes all components for the pumps. It is organized in multiple levels
        (hierarchical) with the following structure. Description in brackets is the pyomo component type.

        pump_block, indexed by pump slots (Block)
            In each slot there can be a different pump type. dis_pump_types (Disjunct)
                Each pump type is modelled as a block: pump_performance_block (Block)
                    Each pump type block (pump_performance_block) contains a disjunct for on-off scheduling
        """

        coeff = self.fitted_performance.coefficients

        configuration = energyhub.configuration
        economics = self.economics
        discount_rate = set_discount_rate(configuration, economics)
        annualization_factor = annualize(discount_rate, economics.lifetime)

        capex_pumps = {}
        capex_pumps[0] = 0
        capex_pumps[1] = annualization_factor * coeff['capex_pumps']

        # Pump Performance
        s_indicators_install = range(0, 2)

        def pump_install_dis_init(dis, pump_slot, ind):
            """
            Disjunct deciding for each slot if installed or not
            """
            if ind == 0:  # not install

                # flow and power constraints
                def init_inflow_not_installed(const, t):
                    return b_tec.var_inflow_pump[t, pump_slot] == 0
                dis.const_inflow_not_installed = Constraint(self.set_t_full, rule=init_inflow_not_installed)

                def init_input_not_installed(const, t):
                    return b_tec.var_input_pump[t, pump_slot] == 0
                dis.const_input_not_installed = Constraint(self.set_t_full, rule=init_input_not_installed)

                # CAPEX constraint
                def init_pump_not_installed_capex(const):
                    return b_tec.var_capex_pump[pump_slot] == 0
                dis.const_pump_not_installed_capex = Constraint(rule=init_pump_not_installed_capex)

            elif ind == 1:  # install

                # CAPEX constraint
                def init_pump_installed_capex(const):
                    return b_tec.var_capex_pump[pump_slot] == (capex_pumps[ind] * b_tec.var_designflow_single_pump)

                dis.const_pump_installed_capex = Constraint(rule=init_pump_installed_capex)

                def pump_performance_block_init(b_pump_performance):

                    # alpha1 = self.performance_data['pump_performance'][pump_names[type]]['Q_in']['alpha1']
                    # alpha2 = self.performance_data['pump_performance'][pump_names[type]]['Q_in']['alpha2']
                    # bp_x = self.performance_data['pump_performance'][pump_names[type]]['Q_in']['bp_x']

                    beta1 = [1.8]
                    beta2 = [0]
                    bp_x = [0.1, 1]

                    s_indicators_onoff = range(0, len(bp_x))

                    def pump_onoff_dis_init(dis, t, ind):
                        if ind == 0:  # off

                            def init_inflow_off(const):
                                return b_tec.var_inflow_pump[t, pump_slot] == 0
                            dis.const_inflow_off = Constraint(rule=init_inflow_off)

                            def init_input_off(const):
                                return b_tec.var_input_pump[t, pump_slot] == 0
                            dis.const_input_off = Constraint(rule=init_input_off)

                        elif ind == 1:  # on
                            def init_inflow_lb(const):
                                return (b_tec.var_inflow_pump[t, pump_slot] >= bp_x[ind - 1] *
                                        b_tec.var_designflow_single_pump)
                            dis.const_inflow_lb = Constraint(rule=init_inflow_lb)

                            def init_inflow_ub(const):
                                return (b_tec.var_inflow_pump[t, pump_slot] <= bp_x[ind] *
                                        b_tec.var_designflow_single_pump)
                            dis.const_inflow_ub = Constraint(rule=init_inflow_ub)

                            def init_input_on(const):
                                return (b_tec.var_input_pump[t, pump_slot] ==
                                        beta1[ind - 1] * b_tec.var_designpower_single_pump +
                                        beta2[ind - 1] * b_tec.var_inflow_pump[t, pump_slot])
                            dis.const_input_on = Constraint(rule=init_input_on)

                        return dis

                    b_pump_performance.dis_pump_onoff = Disjunct(self.set_t_full, s_indicators_onoff,
                                                                       rule=pump_onoff_dis_init)

                    def bind_disjunctions_pump_onoff(dis, t):
                        return [b_pump_performance.dis_pump_onoff[t, i] for i in s_indicators_onoff]

                    b_pump_performance.disjunction_pump_onoff = Disjunction(self.set_t_full,
                                                                                  rule=bind_disjunctions_pump_onoff)
                    b_pump_performance = perform_disjunct_relaxation(b_pump_performance,
                                                                        method='gdp.hull')

                    return b_pump_performance

                dis.pump_performance_block = Block(rule=pump_performance_block_init)

            return dis

        b_tec.dis_pump_install = Disjunct(b_tec.set_pump_slots, s_indicators_install, rule=pump_install_dis_init)

        def bind_disjunctions_pump_install(dis, pump_slot):
            return [b_tec.dis_pump_install[pump_slot, i] for i in s_indicators_install]
        b_tec.disjunction_pump_install = Disjunction(b_tec.set_pump_slots, rule=bind_disjunctions_pump_install)
        b_tec = perform_disjunct_relaxation(b_tec, method='gdp.hull')

        return b_tec

    def report_results(self, b_tec):
        """
        Function to report results of technologies after optimization

        :param b_tec: technology model block
        :return: dict results: holds results
        """
        super(OceanBattery3, self).report_results(b_tec)

        self.results['time_dependent']['storagelevel'] = [b_tec.var_storage_level[t].value for t in self.set_t_full]
        self.results['time_dependent']['total_inflow'] = [b_tec.var_total_inflow[t].value for t in self.set_t_full]
        self.results['time_dependent']['total_outflow'] = [b_tec.var_total_outflow[t].value for t in self.set_t_full]

        # TODO rewrite the results reporting according to new (block) structures.
        for pump in b_tec.set_pump_slots:
            self.results['time_dependent']['var_inflow' + str(pump)] = [b_tec.var_inflow_pump[t, pump].value for t in self.set_t]
            self.results['time_dependent']['var_input' + str(pump)] = [b_tec.var_input_pump[t, pump].value for t in self.set_t]

        for turb in b_tec.set_pump_slots:
            self.results['time_dependent']['var_outflow' + str(turb)] = [b_tec.var_outflow_turbine[t, turb].value for t in self.set_t]
            self.results['time_dependent']['var_output' + str(turb)] = [b_tec.var_output_turbine[t, turb].value for t in self.set_t]

        design = {}
        design['reservoir_size'] = b_tec.var_size.value
        design['single_pump_designflow'] = b_tec.var_designflow_single_pump.value
        design['single_pump_designpower'] = b_tec.var_designpower_single_pump.value
        design['single_turbine_designflow'] = b_tec.var_designflow_single_turbine.value
        design['single_turbine_designpower'] = b_tec.var_designpower_single_turbine.value

        for pump in b_tec.set_pump_slots:
            design['pump_' + str(pump) + '_capex'] = b_tec.var_capex_pump[pump].value

        for turb in b_tec.set_pump_slots:
            design['turbine_' + str(turb) + '_capex'] = b_tec.var_capex_turbine[turb].value

        design_df = pd.DataFrame(data=design, index=[0]).T

        self.results['specific_design'] = design_df

        return self.results