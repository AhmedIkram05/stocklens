// Allow deep imports from react-native internals used by tests/FW.
// Jest mocks require the exact module path that RN's index.js resolves.
declare module 'react-native/Libraries/Utilities/useWindowDimensions';
