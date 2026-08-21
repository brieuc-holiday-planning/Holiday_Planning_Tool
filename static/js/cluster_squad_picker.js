/* Cluster -> squad cascading picker, shared by the squad calendar and
 * squad metrics pages. All clusters/squads are rendered server-side as
 * <option>s up front (each squad option tagged with data-cluster and
 * data-url); this just filters which squad options are visible for the
 * chosen cluster and navigates on squad selection. */
function initClusterSquadPicker(clusterSelectId, squadSelectId) {
  var clusterSelect = document.getElementById(clusterSelectId);
  var squadSelect = document.getElementById(squadSelectId);
  if (!clusterSelect || !squadSelect) return;

  function squadsInSelectedCluster() {
    var clusterId = String(clusterSelect.value);
    return Array.prototype.filter.call(squadSelect.options, function (opt) {
      return String(opt.dataset.cluster) === clusterId;
    });
  }

  // Narrows the squad list to the chosen cluster and makes sure the squad
  // shown belongs to it. Returns the squad options for that cluster.
  function applyClusterFilter() {
    var visible = squadsInSelectedCluster();
    Array.prototype.forEach.call(squadSelect.options, function (opt) {
      opt.hidden = visible.indexOf(opt) === -1;
    });
    var selected = squadSelect.selectedOptions[0];
    if ((!selected || selected.hidden) && visible.length) {
      squadSelect.selectedIndex = visible[0].index;
    }
    return visible;
  }

  function navigateTo(opt) {
    if (!opt || !opt.dataset.url) return; // e.g. a cluster with no squads yet
    if (opt.dataset.url === window.location.pathname) return; // already here
    window.location.href = opt.dataset.url;
  }

  // A squad belongs to exactly one cluster, so changing cluster always
  // leaves the current squad behind - the page must follow to that
  // cluster's first squad. Note this cannot rely on the squad <select>
  // firing its own change event: assigning a selection from code never
  // fires one, which is why picking a cluster used to update both
  // dropdowns while the calendar/metrics below kept showing the old squad.
  clusterSelect.addEventListener("change", function () {
    navigateTo(applyClusterFilter()[0]);
  });

  squadSelect.addEventListener("change", function () {
    navigateTo(squadSelect.selectedOptions[0]);
  });

  // Initial pass only narrows the list to the cluster already being shown;
  // it must never navigate, or every page load would bounce.
  applyClusterFilter();
}
