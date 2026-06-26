/**
 * Mock component for SVG imports in React Native tests.
 * Renders a simple View with SVG props as data attributes for inspection.
 */

const React = require('react');
const { View } = require('react-native');

const SvgMock = ({ children = null, width, height, viewBox, fill, ...props }) => {
  // Render a <View> that carries the svg props so tests can inspect them.
  // We attach a testID for easy querying in react-native-testing-library.
  return React.createElement(
    View,
    {
      testID: 'svg-mock',
      accessible: false,
      // expose common SVG props as data attributes so that
      // snapshots or prop inspections can validate them.
      'data-svg-width': width,
      'data-svg-height': height,
      'data-svg-viewbox': viewBox,
      'data-svg-fill': fill,
      ...props,
    },
    children,
  );
};

SvgMock.displayName = 'SvgMock';

module.exports = SvgMock;
module.exports.ReactComponent = SvgMock;
