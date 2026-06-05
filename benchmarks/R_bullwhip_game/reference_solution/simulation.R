#' Bullwhip Game Reference Implementation
#'
#' This is the reference solution for evaluating AI-generated implementations.
#' @param demand_mean Mean demand per period
#' @param demand_sd Standard deviation of demand
#' @param periods Number of simulation periods
#' @param seed Random seed for reproducibility
#' @return A tibble with simulation results
#' @export
simulate_bullwhip <- function(demand_mean = 10, demand_sd = 2, periods = 50, seed = 42L) {
  set.seed(seed)

  # Generate random demand
  demand <- rnorm(n = periods, mean = demand_mean, sd = demand_sd) %>%
    round() %>%
    pmax(0)  # Ensure non-negative demand

  # Simple supply chain with 4 stages
  supply_chain <- tibble(
    period = 1:periods,
    customer = demand,
    retailer = lag(customer, default = demand_mean),
    wholesaler = lag(retailer, default = demand_mean),
    distributor = lag(wholesaler, default = demand_mean),
    manufacturer = lag(distributor, default = demand_mean)
  )

  # Calculate bullwhip effect (variance amplification)
  variances <- supply_chain %>%
    select(-period) %>%
    map_dbl(var, na.rm = TRUE)

  # Add variance ratios
  supply_chain <- supply_chain %>%
    mutate(
      retailer_var_ratio = var(retailer, na.rm = TRUE) / var(customer, na.rm = TRUE),
      wholesaler_var_ratio = var(wholesaler, na.rm = TRUE) / var(customer, na.rm = TRUE),
      distributor_var_ratio = var(distributor, na.rm = TRUE) / var(customer, na.rm = TRUE),
      manufacturer_var_ratio = var(manufacturer, na.rm = TRUE) / var(customer, na.rm = TRUE)
    )

  return(supply_chain)
}