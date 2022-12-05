from pyomo.environ import *
from pyomo.environ import units as u
from src.model_construction.construct_technology import add_technologies

def add_nodes(model, data):
    r"""
    Adds all nodes with respective data to the model

    This function initializes parameters and decision variables for all considered nodes. It also adds all technologies\
    that are installed at the node (see :func:`~add_technologies`). For each node, it adds one block indexed by the \
    set of all nodes. As such, the function constructs:

    > node blocks, indexed by :math:`N` > technology blocks, indexed by :math:`Tec_n, n \in N`

    **Set declarations:**

    - Set for all technologies :math:`S_n` at respective node :math:`n` : :math:`S_n, n \in N` (this is a duplicate of a set already initialized in ``self.model.set_technologies``).

    **Parameter declarations:**

    - Demand for each time step
    - Import Prices for each time step
    - Export Prices for each time step
    - Import Limits for each time step
    - Export Limits for each time step
    - Emission Factors for each time step

    **Variable declarations:**

    - Import Flow for each time step
    - Export Flow for each time step
    - Cost at node (includes technology costs (CAPEX, OPEX) and import/export costs), see constraint declarations

    **Constraint declarations**

    - Cost at node:

    .. math::
        C_n = \
        \sum_{tec \in Tec_n} CAPEX_{tec} + \
        \sum_{tec \in Tec_n} OPEXfix_{tec} + \
        \sum_{tec \in Tec_n} \sum_{t \in T} OPEXvar_{t, tec} + \\
        \sum_{car \in Car} \sum_{t \in T} import_{t, car} pImport_{t, car} - \
        \sum_{car \in Car} \sum_{t \in T} export_{t, car} pExport_{t, car}

    **Block declarations:**

    - Technologies at node

    :param obj model: instance of a pyomo model
    :param DataHandle data: instance of a DataHandle
    :return: model
    """
    def init_node_block(b_node, nodename):

        # SETS: Get technologies for each node and make it a set for the block
        b_node.set_tecsAtNode = Set(initialize=model.set_technologies[nodename])

        # PARAMETERS
        # Demand
        # TODO: check if or for
        def init_demand(para, t, car):
            if nodename in data.node_data:
                return data.node_data[nodename]['demand'][car][t - 1]
        b_node.para_demand = Param(model.set_t, model.set_carriers, rule=init_demand, units=u.MW)

        # Import Prices
        def init_import_price(para, t, car):
            if nodename in data.node_data:
                return data.node_data[nodename]['import_prices'][car][t - 1]
        b_node.para_import_price = Param(model.set_t, model.set_carriers, rule=init_import_price, units=u.EUR / u.MWh)

        # Export Prices
        def init_export_price_init(para, t, car):
            if nodename in data.node_data:
                return data.node_data[nodename]['export_prices'][car][t - 1]
        b_node.para_export_price = Param(model.set_t, model.set_carriers, rule=init_export_price_init, units=u.EUR / u.MWh)

        # Import Limit
        def init_import_limit(para, t, car):
            if nodename in data.node_data:
                return data.node_data[nodename]['import_limit'][car][t - 1]
        b_node.para_import_limit = Param(model.set_t, model.set_carriers, rule=init_import_limit, units=u.MW)

        # Export Limit
        def init_export_limit(para, t, car):
            if nodename in data.node_data:
                return data.node_data[nodename]['export_limit'][car][t - 1]
        b_node.para_export_limit = Param(model.set_t, model.set_carriers, rule=init_export_limit, units=u.MW)

        # Emission Factor
        # TODO: import and export emissionfactor
        def init_emission_factor(para, t, car):
            if nodename in data.node_data:
                return data.node_data[nodename]['emission_factors'][car][t - 1]
        b_node.para_emission_factor = Param(model.set_t, model.set_carriers, rule=init_emission_factor, units=u.t / u.MW)

        # DECISION VARIABLES
        # Interaction with network/system boundaries
        def init_import_bounds(var, t, car):
            return (0, b_node.para_import_limit[t, car])
        b_node.var_import_flow = Var(model.set_t, model.set_carriers, bounds=init_import_bounds, units=u.MW)

        def init_export_bounds(var, t, car):
            return (0, b_node.para_export_limit[t, car])
        b_node.var_export_flow = Var(model.set_t, model.set_carriers, bounds=init_export_bounds, units=u.MW)

        # Cost at node
        b_node.var_cost = Var(units=u.EUR)

        # BLOCKS
        # Add technologies as blocks
        b_node = add_technologies(nodename, b_node, model, data)

        def init_cost_at_node(const):  # var_cost calculation at node per carrier
            return sum(b_node.tech_blocks[tec].var_CAPEX
                       for tec in b_node.set_tecsAtNode) + \
                   sum(sum(b_node.tech_blocks[tec].var_OPEX_variable[t]
                            for tec in b_node.set_tecsAtNode) for t in model.set_t) + \
                   sum(b_node.tech_blocks[tec].var_OPEX_fixed
                        for tec in b_node.set_tecsAtNode) + \
                   sum(sum(b_node.var_import_flow[t, car] * b_node.para_import_price[t, car]
                           for car in model.set_carriers) for t in model.set_t) - \
                   sum(sum(b_node.var_export_flow[t, car] * b_node.para_export_price[t, car]
                           for car in model.set_carriers) for t in model.set_t) == \
                   b_node.var_cost
        b_node.const_cost = Constraint(rule=init_cost_at_node)

    model.node_blocks = Block(model.set_nodes, rule=init_node_block)

    return model







