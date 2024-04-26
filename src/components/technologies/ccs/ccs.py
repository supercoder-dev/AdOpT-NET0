from ....utilities import open_json
import numpy as np
from ...component import ModelComponent


def fit_ccs_data(ccs_data, data):
    """
    Calculates the amount of input (and their bounds) required for each unit of CO2 entering the carbon capture (CC)
    object. So far, only post-combustion MEA has been modelled (based on Eq. 7 in Weimann et Al. (2023), A thermodynamic-based
    mixed-integer linear model of post-combustion carbon capture for reliable use in energy system optimisation
    https://doi.org/10.1016/j.apenergy.2023.120738).

    :param dict ccs_data: performance data of the CCS technology
    :param data: input data
    :return: tec_data


    """

    tec_data = open_json(ccs_data["ccs_type"], data.model_information.tec_data_path)
    performance_data = tec_data["TechnologyPerf"]
    time_steps = len(data.topology.timesteps)

    molar_mass_CO2 = 44.01

    co2_concentration = ccs_data["co2_concentration"]
    carbon_capture_rate = performance_data["capture_rate"]

    # Recalculate min/max size
    tec_data["size_min"] = tec_data["size_min"] * co2_concentration
    tec_data["size_max"] = tec_data["size_max"] * co2_concentration

    # Calculate input ratios
    if "MEA" in ccs_data["ccs_type"]:
        tec_data["TechnologyPerf"]["input_ratios"] = {}
        for car in tec_data["TechnologyPerf"]["input_carrier"]:
            tec_data["TechnologyPerf"]["input_ratios"][car] = (
                tec_data["TechnologyPerf"]["eta"][car]
                + tec_data["TechnologyPerf"]["omega"][car] * co2_concentration
            ) / (co2_concentration * molar_mass_CO2 * 3.6)
    else:
        raise Exception(
            "Only CCS type MEA is modelled so far. ccs_type in the json file of the technology must include MEA"
        )

    # Calculate bounds
    tec_data["TechnologyPerf"]["bounds"] = {}
    tec_data["TechnologyPerf"]["bounds"]["input"] = {}
    tec_data["TechnologyPerf"]["bounds"]["output"] = {}
    for car in tec_data["TechnologyPerf"]["input_carrier"]:
        tec_data["TechnologyPerf"]["bounds"]["input"][car] = np.column_stack(
            (
                np.zeros(shape=(time_steps)),
                np.ones(shape=(time_steps))
                * tec_data["TechnologyPerf"]["input_ratios"][car],
            )
        )
    for car in tec_data["TechnologyPerf"]["output_carrier"]:
        tec_data["TechnologyPerf"]["bounds"]["output"][car] = np.column_stack(
            (
                np.zeros(shape=(time_steps)),
                np.ones(shape=(time_steps)) * carbon_capture_rate,
            )
        )

    return tec_data

    #
    #
    # if self.performance_data['plant_size'] == 'small':
    #
    #     self.economics.capex_data[
    #         'unit_capex'] = 3.44 / convert2t_per_h + 185 * carbon_capture_rate * co2_concentration / convert2t_per_h
    #     self.economics.capex_data['fix_capex'] = 2.17
    #
    # elif self.performance_data['plant_size'] == 'medium':
    #
    #
    #     self.economics.capex_data[
    #         'unit_capex'] = 2.83 / convert2t_per_h + 125 * carbon_capture_rate * co2_concentration / convert2t_per_h
    #     self.economics.capex_data['fix_capex'] = 11.1
    #
    # elif self.performance_data['plant_size'] == 'large':
    #
    #     self.economics.capex_data[
    #         'unit_capex'] = 3.11 / convert2t_per_h + 123 * carbon_capture_rate * co2_concentration / convert2t_per_h
    #     self.economics.capex_data['fix_capex'] = 10.8
    #
    #
