import React from 'react';
import { Button, Tooltip } from 'antd';

import { productWorkflowActionDiagnostic } from './productWorkflowActionRegistry';


type ProductWorkflowUnknownActionProps = {
  action: string;
  surface: 'product-list' | 'product-detail';
  size?: 'small' | 'middle' | 'large';
};


export const ProductWorkflowUnknownAction: React.FC<ProductWorkflowUnknownActionProps> = ({
  action,
  surface,
  size = 'middle',
}) => {
  const diagnostic = productWorkflowActionDiagnostic(action);
  return React.createElement(
    Tooltip,
    { title: diagnostic },
    React.createElement(
      'span',
      {
        title: diagnostic,
        'data-workflow-action-fallback': surface,
        'data-workflow-action': action,
      },
      React.createElement(Button, { size, disabled: true }, '当前版本无法执行'),
    ),
  );
};
