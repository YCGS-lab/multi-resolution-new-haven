import { defineConfig } from "vitepress";
import { withMermaid } from "vitepress-plugin-mermaid";

// Developer documentation, viewed locally (`npm run dev` in docs/).
export default withMermaid(
  defineConfig({
    title: "New Haven at many resolutions",
    description: "How the data pipeline and the map viewer work",
    lang: "en-US",
    cleanUrls: true,
    lastUpdated: false,
    // Pages outside the documentation proper.
    srcExclude: ["README.md", "node_modules/**"],
    // The update procedure in deck-gl-raster.md mentions local servers.
    ignoreDeadLinks: "localhostLinks",
    markdown: {
      // Off: snippets are regions of files, so numbers starting at 1 would mislead.
      lineNumbers: false,
    },
    themeConfig: {
      outline: { level: [2, 3] },
      search: { provider: "local" },
      nav: [
        { text: "Overview", link: "/" },
        { text: "Data pipeline", link: "/pipeline/" },
        { text: "Map viewer", link: "/website/" },
        { text: "Build & deploy", link: "/build/" },
        { text: "Old vs new", link: "/comparison/" },
        { text: "Issues", link: "/issues" },
      ],
      sidebar: [
        {
          text: "Start here",
          items: [
            { text: "Overview", link: "/" },
            { text: "How to read these docs", link: "/guide/reading" },
            { text: "Glossary", link: "/guide/glossary" },
            { text: "Issues and improvements", link: "/issues" },
          ],
        },
        {
          text: "Data pipeline (Python)",
          items: [
            { text: "Overview", link: "/pipeline/" },
            { text: "Views and grids", link: "/pipeline/views-and-grids" },
            { text: "Figures", link: "/pipeline/figures" },
            { text: "Remote services", link: "/pipeline/remote" },
            { text: "Website data and the catalog", link: "/pipeline/website-data" },
            {
              text: "Datasets",
              link: "/pipeline/datasets/",
              collapsed: false,
              items: [
                { text: "Optical imagery", link: "/pipeline/datasets/optical" },
                { text: "Temperature", link: "/pipeline/datasets/temperature" },
                { text: "Water and night lights", link: "/pipeline/datasets/water-and-lights" },
                { text: "Elevation", link: "/pipeline/datasets/elevation" },
                { text: "Vegetation and land cover", link: "/pipeline/datasets/vegetation-and-land-cover" },
                { text: "Radar (NISAR)", link: "/pipeline/datasets/radar" },
                { text: "Street maps and landmarks", link: "/pipeline/datasets/maps-and-landmarks" },
              ],
            },
          ],
        },
        {
          text: "Map viewer (JavaScript)",
          items: [
            { text: "Overview", link: "/website/" },
            { text: "Catalog and coordinates", link: "/website/catalog" },
            { text: "Map views", link: "/website/map-views" },
            { text: "COG layers (deck.gl-raster)", link: "/website/cog-layers" },
            { text: "Image-service layers", link: "/website/image-services" },
            { text: "Viewer, compare and grid", link: "/website/viewer-and-grid" },
            { text: "Page, picker and URL state", link: "/website/page" },
          ],
        },
        {
          text: "Build, deploy, test",
          items: [
            { text: "Overview", link: "/build/" },
            { text: "Vendored bundle", link: "/build/vendor" },
            { text: "Local development", link: "/build/local" },
            { text: "Deployment (AWS)", link: "/build/deploy" },
            { text: "Fixtures and benchmark", link: "/build/benchmark" },
          ],
        },
        {
          text: "Old vs new renderer",
          items: [
            { text: "Overview", link: "/comparison/" },
            { text: "Reading COGs", link: "/comparison/reading" },
            { text: "Coloring", link: "/comparison/coloring" },
            { text: "Views and compositing", link: "/comparison/views" },
            { text: "Basemaps and image services", link: "/comparison/services" },
            { text: "Performance", link: "/comparison/performance" },
            { text: "Migration report (PR write-up)", link: "/deck-gl-raster" },
            { text: "Benchmark results", link: "/benchmarks/2026-10-10" },
          ],
        },
      ],
    },
    // A fixed system font: mermaid sizes boxes with the font it measures, and
    // the theme's web font loading later would overflow them.
    mermaid: { fontFamily: "Arial, Helvetica, sans-serif", flowchart: { padding: 12 } },
  }),
);
