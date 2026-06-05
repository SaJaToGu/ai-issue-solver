testthat::test_check("Bullwhip Game Simulation")

# Test basic simulation properties
test_that("simulation produces expected output structure", {
  result <- simulate_bullwhip(periods = 10, seed = 123L)

  expect_is(result, "tibble")
  expect_equal(nrow(result), 10)
  expect_equal(ncol(result), 13)  # 1 period + 4 stages + 4 variance ratios

  # Check column names
  expected_cols <- c(
    "period", "customer", "retailer", "wholesaler", "distributor", "manufacturer",
    "retailer_var_ratio", "wholesaler_var_ratio", "distributor_var_ratio", "manufacturer_var_ratio"
  )
  expect_equal(colnames(result), expected_cols)
})

# Test reproducibility with fixed seed
test_that("simulation is reproducible with fixed seed", {
  set.seed(42L)
  run1 <- simulate_bullwhip(periods = 5, seed = 42L)

  set.seed(42L)
  run2 <- simulate_bullwhip(periods = 5, seed = 42L)

  expect_identical(run1, run2)
})

# Test variance amplification (bullwhip effect)
test_that("simulation shows variance amplification", {
  result <- simulate_bullwhip(periods = 100, seed = 456L)

  customer_var <- var(result$customer, na.rm = TRUE)
  manufacturer_var <- var(result$manufacturer, na.rm = TRUE)

  expect_gt(manufacturer_var, customer_var, info = "Manufacturer variance should exceed customer variance")
  expect_gt(result$manufacturer_var_ratio[1], 1, info = "Variance ratio should exceed 1")
})

# Test non-negative demand
test_that("demand values are non-negative", {
  result <- simulate_bullwhip(periods = 1000, seed = 789L)
  expect_true(all(result$customer >= 0, na.rm = TRUE))
})