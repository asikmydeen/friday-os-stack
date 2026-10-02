# friday-core

Chart for the core services, for someone who already runs Kubernetes.
It is not how a phone reaches this appliance. Compose stays the contract.

Every deployment has one replica and a recreate strategy. The Friday
volume is mounted only by the friday deployment. The claim uses
ReadWriteOncePod when the cluster supports it, and ReadWriteOnce
otherwise. Recreate still removes the old pod before the new one mounts,
so two pods do not hold that volume together.

The ollama deployment is the embed worker. The memory-mcp deployment is
the index reconciler. Both use the same singleton rule.

Headscale, cloudflared, and the browser session are not in this chart.
Coder is a dependency this chart does not deploy. Catalog apps stay out.
The image tags are local names, not a published registry. The chart does
not create the secret friday-core and does not contain its values. One
fire writes these files. It does not contact a cluster and does not
start a pod.
