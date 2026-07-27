"""Identifying latent return drivers using PCA (book Chapter 7 recipe)."""

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from openbb import obb
import matplotlib.pyplot as plt

obb.user.preferences.output_type = "dataframe"

# 1. Download data for gold mining stocks and healthcare stocks, compute daily returns
symbols = ["NEM", "RGLD", "SSRM", "CDE", "LLY", "UNH", "JNJ", "MRK"]

data = obb.equity.price.historical(
    symbols,
    start_date="2020-01-01",
    end_date="2022-12-31",
    provider="yfinance",
).pivot(columns="symbol", values="close")

print(data.head())
returns = data.pct_change().dropna()


print(returns.head())
# # 2. Run the PCA using three components and fit the model
# pca = PCA(n_components=3)
# pca.fit(returns)

# # 3. Extract the explained variance ratio and the principal components
# pct = pca.explained_variance_ratio_
# pca_components = pca.components_

# # 4. Plot per-component contribution and cumulative percent of explained variance
# cum_pct = np.cumsum(pct)
# x = np.arange(1, len(pct) + 1, 1)

# plt.subplot(1, 2, 1)
# plt.bar(x, pct * 100, align="center")
# plt.title("Contribution (%)")
# plt.xticks(x)
# plt.xlim([0, 4])
# plt.ylim([0, 100])

# plt.subplot(1, 2, 2)
# plt.plot(x, cum_pct * 100, "ro-")
# plt.title("Cumulative contribution (%)")
# plt.xticks(x)
# plt.xlim([0, 4])
# plt.ylim([0, 100])
# plt.show()

# # 5. Transform returns into the statistical risk factors (the principal components)
# X = np.asarray(returns)
# factor_returns = X.dot(pca_components.T)
# factor_returns = pd.DataFrame(
#     columns=["f1", "f2", "f3"],
#     index=returns.index,
#     data=factor_returns,
# )
# print(factor_returns.head())

# # 6. Create each asset's exposure to the three factors
# factor_exposures = pd.DataFrame(
#     index=["f1", "f2", "f3"],
#     columns=returns.columns,
#     data=pca_components,
# ).T
# print(factor_exposures)

# # 7. Visualize each asset's exposure to the first two principal components
# labels = factor_exposures.index
# data = factor_exposures.values

# plt.scatter(data[:, 0], data[:, 1])
# plt.xlabel("factor exposure of PC1")
# plt.ylabel("factor exposure of PC2")

# for label, x, y in zip(labels, data[:, 0], data[:, 1]):
#     plt.annotate(
#         label,
#         xy=(x, y),
#         xytext=(-20, 20),
#         textcoords="offset points",
#         arrowprops=dict(
#             arrowstyle="->",
#             connectionstyle="arc3,rad=0",
#         ),
#     )

# plt.show()
