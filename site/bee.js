// Shared decorative ASCII bee. Lives in one place; every page renders it with
// <lilbee-bee></lilbee-bee>. aria-hidden because it is purely decorative.
const LILBEE_BEE_ART = "     %           %\n         %           %\n            %           %\n               %          %\n                 %          %\n                   %          %                   :::\n                    %          %                ::::::\n                 %%%%%%  %%%%%%%%%            ::::::::\n              %%%%%ZZZZ%%%%%%   %%%ZZZZ     ::::::::::         ::::::\n             %%%ZZZZZ%%%%%%%%%%%%%%ZZZZZZ  :::::::::::    :::::::::::::::::\n             ZZZ%ZZZ%%%%%%%%%%%%%%%ZZZZZZZ::::::::::***:::::::::::::::::::::\n          ZZZ%ZZZZZZ%%%%%%%%%%%%%%ZZZZZZZZZ::::::***:::::::::::::::::::::::\n        ZZZ%ZZZZZZZZZZ%%%%%%%%%%ZZZZZZ%ZZZZ:::***:::::::::::::::::::::::\n       ZZ%ZZZZZZZZZZZZZZZZZZZZZZZ%%%%% %ZZZ:**::::::::::::::::::::::\n      ZZ%ZZZZZZZZZZZZZZZZZZZ%%%%% | | %ZZZ *:::::::::::::::::::\n      Z%ZZZZZZZZZZZZZZZ%%%%%%%%%%%%%%%ZZZ::::::::::::::::::::::::::\n       ZZZZZZZZZZZ%%%%%ZZZZZZZZZZZZZZZZZ%%%%:::ZZZZ:::::::::::::::::\n         ZZZZ%%%%%ZZZZZZZZZZZZZZZZZZ%%%%%ZZZ%%ZZZ%ZZ%%*:::::::::::\n            ZZZZZZZZZZZZZZZZZZ%%%%%%%%%ZZZZZZZZZZ%ZZ%:::*:::::::\n            *:::%%%%%%%%%%%%%%%%%%%%%%%ZZZZZZZZZZ%%%*::::*::::\n          *:::::::%%%%%%%%%%%%%%%%%%%%%%%ZZZZZ%%      *:::Z\n         **:ZZZZ:::%%%%%%%%%%%%%%%%%%%%%%%%%%%ZZ      ZZZZZ\n        *:ZZZZZZZ       %%%%%%%%%%%%%%%%%%%%%ZZZZ    ZZZZZZZ\n       *::::ZZZZZZ         %%%%%%%%%%%%%%%ZZZZZZZ      ZZZ\n        *::ZZZZZZ           Z%%%%%%%%%%%ZZZZZZZ%%\n          ZZZZ              ZZZZZZZZZZZZZZZZ%%%%%\n                           %%%ZZZZZZZZZZZ%%%%%%%%\n                          Z%%%%%%%%%%%%%%%%%%%%%\n                          ZZ%%%%%%%%%%%%%%%%%%%\n                          %ZZZZZZZZZZZZZZZZZZZ\n                          %%ZZZZZZZZZZZZZZZZZ\n                           %%%%%%%%%%%%%%%%\n                            %%%%%%%%%%%%%\n                             %%%%%%%%%\n                              ZZZZ\n                              ZZZ\n                             ZZ\n                            Z";

customElements.define(
  "lilbee-bee",
  class extends HTMLElement {
    connectedCallback() {
      this.style.display = "contents";
      const pre = document.createElement("pre");
      pre.textContent = LILBEE_BEE_ART;
      const aside = document.createElement("aside");
      aside.className = "bee-art";
      aside.setAttribute("aria-hidden", "true");
      aside.appendChild(pre);
      this.replaceChildren(aside);
    }
  },
);
