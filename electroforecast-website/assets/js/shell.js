/* ElectroForecast — shared app shell (sidebar + topbar) */
(function(){
  const NAV = [
    { group:"Overview", items:[
      { key:"user-portal", label:"My Energy Portal", href:"user-portal.html", icon:"home", roles:["household"] },
      { key:"admin-dashboard", label:"Admin Dashboard", href:"admin-dashboard.html", icon:"grid", roles:["admin","guimelco","researcher"] },
      { key:"dashboard", label:"Forecast Dashboard", href:"dashboard.html", icon:"trending-up", roles:["admin","guimelco","researcher"] },
    ]},
    { group:"Forecasting", items:[
      { key:"forecasting", label:"Forecasting", href:"forecasting.html", icon:"trending-up", roles:["admin","guimelco","researcher","household"] },
      { key:"demand", label:"Demand Classification", href:"demand-classification.html", icon:"activity", roles:["admin","guimelco","researcher","household"] },
      { key:"explainable", label:"Explainable AI", href:"explainable-ai.html", icon:"cpu", roles:["admin","guimelco","researcher","household"] },
    ]},
    { group:"Crowdsourcing", items:[
      { key:"crowdsourced", label:"Crowdsourced Ratings", href:"crowdsourced-ratings.html", icon:"database", roles:["household"] },
      { key:"appliances", label:"My Appliances", href:"my-appliances.html", icon:"zap", roles:["household"] },
      { key:"submissions", label:"My Submissions", href:"my-submissions.html", icon:"clipboard", roles:["household"] },
      { key:"consumption", label:"Monthly Consumption", href:"monthly-consumption.html", icon:"bar-chart-2", roles:["household"] },
    ]},
    { group:"Data & Reports", items:[
      { key:"explorer", label:"Validated Data", href:"data-explorer.html", icon:"database", roles:["admin","guimelco","researcher"] },
      { key:"reports", label:"Reports", href:"reports.html", icon:"file-text", roles:["admin","guimelco","researcher"] },
      { key:"leaderboard", label:"Contributors", href:"leaderboard.html", icon:"award", roles:["admin","guimelco","researcher"] },
    ]},
    { group:"Administration", items:[
      { key:"admin-ratings", label:"Review Submissions", href:"admin-dashboard.html#review", icon:"check-square", roles:["admin"] },
      { key:"admin-users", label:"User Management", href:"admin-dashboard.html#users", icon:"shield", roles:["admin"] },
    ]},
    { group:"System", items:[
      { key:"notifications", label:"Notifications", href:"notifications.html", icon:"bell", roles:["admin","guimelco","researcher","household"] },
      { key:"settings", label:"Settings", href:"settings.html", icon:"settings", roles:["admin","guimelco","researcher","household"] },
      { key:"about", label:"About", href:"about.html", icon:"info", roles:["admin","guimelco","researcher","household"] },
    ]},
  ];

  const BRAND_LOGO = `<img src="assets/images/electroforecast-logo.png" alt="ElectroForecast logo">`;

  function initials(name){
    return String(name || "User").split(/\s+/).slice(0,2).map(part=>part[0]).join("").toUpperCase();
  }

  function defaultUser(){
    try { return JSON.parse(sessionStorage.getItem("electro_user")) || {}; }
    catch (_) { return {}; }
  }

  function sidebarHTML(active, user){
    const role = user.role || "admin";
    const groups = NAV.map(g => {
      const items = g.items.filter(item => !item.roles || item.roles.includes(role));
      if (!items.length) return "";
      return `
      <div class="nav-section-label">${g.group}</div>
      <div class="nav-list">
        ${items.map(it => `
          <a class="nav-item ${it.key===active?'active':''}" href="${it.href}">
            <i data-feather="${it.icon}"></i><span>${it.label}</span>
          </a>`).join("")}
      </div>`;
    }).join("");
    const home = role === "household" ? "user-portal.html" : "admin-dashboard.html";
    const name = user.full_name || "Greence Mark";
    const roleLabel = role === "guimelco" ? "GUIMELCO Staff" : role.charAt(0).toUpperCase()+role.slice(1);

    return `
    <aside class="sidebar" id="sidebar">
      <a class="sidebar-brand" href="${home}" aria-label="ElectroForecast home">
        <div class="logo-mark">${BRAND_LOGO}</div>
        <div>
          <div class="brand-name">ElectroForecast</div>
          <div class="brand-tag">Smart Energy Insights</div>
        </div>
      </a>
      ${groups}
      <div class="sidebar-footer">
        <div class="avatar">${initials(name)}</div>
        <div class="who">
          <div class="name">${name}</div>
          <div class="role">${roleLabel}</div>
        </div>
        <button title="Sign out" onclick="window.ElectroAPI ? ElectroAPI.logout() : (window.location.href='login.html')"><i data-feather="log-out"></i></button>
      </div>
    </aside>
    <button class="sidebar-scrim" id="sidebarScrim" aria-label="Close navigation"></button>`;
  }

  function topbarHTML(title, opts, user){
    opts = opts || {};
    const showRange = opts.dateRange !== false;
    return `
    <header class="topbar">
      <div class="topbar-left">
        <button class="burger" id="burgerBtn"><i data-feather="menu"></i></button>
        <div class="page-title">${title}</div>
      </div>
      <div class="topbar-right">
        ${showRange ? `<div class="date-range"><i data-feather="calendar"></i><span>May 21 – May 27, 2026</span></div>` : ``}
        <button class="icon-btn" onclick="window.location.href='notifications.html'"><i data-feather="bell"></i><span class="dot"></span></button>
        <div class="topbar-avatar">${initials(user.full_name || "Greence Mark")}</div>
      </div>
    </header>`;
  }

  window.ElectroShell = {
    mount(active, title, opts){
      if (!document.querySelector('link[rel~="icon"]')) {
        const favicon = document.createElement('link');
        favicon.rel = 'icon';
        favicon.type = 'image/png';
        favicon.href = 'assets/images/electroforecast-logo.png';
        document.head.appendChild(favicon);
      }
      const user = defaultUser();
      this.state = { active, title, opts:opts || {}, user };
      document.getElementById('shell-sidebar').innerHTML = sidebarHTML(active, user);
      document.getElementById('shell-topbar').innerHTML = topbarHTML(title, opts, user);
      if (window.feather) feather.replace({ 'stroke-width': 2, width: 17, height: 17 });
      const burger = document.getElementById('burgerBtn');
      if (burger){
        const sidebar = document.getElementById('sidebar');
        const scrim = document.getElementById('sidebarScrim');
        const closeSidebar = () => {
          sidebar.classList.remove('open');
          scrim.classList.remove('open');
          document.body.classList.remove('nav-open');
        };
        burger.addEventListener('click', () => {
          const isOpen = sidebar.classList.toggle('open');
          scrim.classList.toggle('open', isOpen);
          document.body.classList.toggle('nav-open', isOpen);
        });
        scrim.addEventListener('click', closeSidebar);
        sidebar.querySelectorAll('.nav-item').forEach(link => link.addEventListener('click', closeSidebar));
        document.addEventListener('keydown', event => {
          if (event.key === 'Escape') closeSidebar();
        });
      }
    },
    setUser(user){
      sessionStorage.setItem("electro_user", JSON.stringify(user));
      if (this.state) this.mount(this.state.active, this.state.title, this.state.opts);
    }
  };
})();
