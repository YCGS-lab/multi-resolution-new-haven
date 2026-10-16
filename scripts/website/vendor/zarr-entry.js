// Zarr reading for the website (website/vendor/zarrita.js): zarrita, with
// its codecs (blosc, zstd, lz4, gzip, zlib). A separate bundle from
// entry.js so the deck.gl bundle stays unchanged; built by build.mjs.

export { FetchStore, get, open, slice, withByteCaching, withMaybeConsolidatedMetadata } from "zarrita";
