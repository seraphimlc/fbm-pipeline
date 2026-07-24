import { existsSync, statSync } from 'node:fs';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

import { mutationExportAllowlist } from './mutation-export-allowlist.mjs';


const scriptPath = fileURLToPath(import.meta.url);
const scriptDir = path.dirname(scriptPath);
const defaultFrontendRoot = path.resolve(scriptDir, '..');
const defaultRepoRoot = path.resolve(defaultFrontendRoot, '..');
const MUTATION_METHODS = new Set(['post', 'put', 'patch', 'delete']);
const ALLOWLIST_CLASSIFICATIONS = new Set(['test-only', 'internal', 'unused']);
const OWNER_CONTRACT_FIELDS = new Set([
  'owner_component',
  'owner_state',
  'loading_state',
  'catch_policy',
  'finally_policy',
  'playwright_case',
]);
const WORKFLOW_BINDINGS_EXPORT = 'PRODUCT_WORKFLOW_API_CLIENT_BINDINGS';
const WORKFLOW_DISPATCH_EXPORT = 'dispatchProductWorkflowAction';
const DEFAULT_REQUIRED_ROOTS = [
  'src/pages/ProductList.tsx',
  'src/pages/ProductDetail.tsx',
  'src/pages/CatalogList.tsx',
  'src/pages/TaskRunCenter.tsx',
];
const SCAN_DIRECTORIES = ['src/pages', 'src/components', 'src/hooks'];


const slash = (value) => value.split(path.sep).join('/');


function sourceKind(filePath) {
  return filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
}


async function parseSource(filePath) {
  return ts.createSourceFile(
    filePath,
    await readFile(filePath, 'utf8'),
    ts.ScriptTarget.Latest,
    true,
    sourceKind(filePath),
  );
}


function hasExportModifier(node) {
  return Boolean(node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword));
}


function collectAllExportNames(sourceFile) {
  const names = new Set();
  for (const statement of sourceFile.statements) {
    if (!hasExportModifier(statement)) continue;
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (ts.isIdentifier(declaration.name)) names.add(declaration.name.text);
      }
      continue;
    }
    if (
      (ts.isFunctionDeclaration(statement)
        || ts.isClassDeclaration(statement)
        || ts.isInterfaceDeclaration(statement)
        || ts.isTypeAliasDeclaration(statement)
        || ts.isEnumDeclaration(statement))
      && statement.name
    ) {
      names.add(statement.name.text);
    }
  }
  return names;
}


function mutationCallsInside(node) {
  const calls = [];
  const visit = (child) => {
    if (
      ts.isCallExpression(child)
      && ts.isPropertyAccessExpression(child.expression)
      && ts.isIdentifier(child.expression.expression)
      && child.expression.expression.text === 'api'
      && MUTATION_METHODS.has(child.expression.name.text)
    ) {
      calls.push(child);
    }
    ts.forEachChild(child, visit);
  };
  if (node) visit(node);
  return calls;
}


function collectMutatingExports(sourceFile) {
  const exports = [];
  for (const statement of sourceFile.statements) {
    if (!hasExportModifier(statement)) continue;
    const candidates = [];
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (ts.isIdentifier(declaration.name)) {
          candidates.push({ name: declaration.name.text, body: declaration.initializer });
        }
      }
    } else if (ts.isFunctionDeclaration(statement) && statement.name) {
      candidates.push({ name: statement.name.text, body: statement.body });
    }
    for (const candidate of candidates) {
      const calls = mutationCallsInside(candidate.body);
      if (calls.length === 0) continue;
      if (calls.length !== 1) {
        throw new Error(`mutating export ${candidate.name} must contain exactly one api mutation call`);
      }
      const call = calls[0];
      const expression = call.expression;
      exports.push({
        client: candidate.name,
        method: expression.name.text,
        endpoint: call.arguments[0]?.getText(sourceFile) || '<missing-endpoint>',
      });
    }
  }
  return exports.sort((left, right) => left.client.localeCompare(right.client));
}


async function listTypeScriptFiles(directory) {
  if (!existsSync(directory)) return [];
  const files = [];
  const visit = async (current) => {
    const entries = await readdir(current, { withFileTypes: true });
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      const entryPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        await visit(entryPath);
      } else if (/\.tsx?$/.test(entry.name)) {
        files.push(path.resolve(entryPath));
      }
    }
  };
  await visit(directory);
  return files;
}


function resolveLocalModule(importer, specifier) {
  if (!specifier.startsWith('.')) return null;
  const base = path.resolve(path.dirname(importer), specifier);
  const candidates = [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    path.join(base, 'index.ts'),
    path.join(base, 'index.tsx'),
  ];
  return candidates.find((candidate) => existsSync(candidate) && statSync(candidate).isFile()) || null;
}


function pathInsideAny(candidate, roots) {
  return roots.some((root) => {
    const relative = path.relative(root, candidate);
    return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
  });
}


async function collectRequiredReachableFiles(requiredRoots, scopeRoots) {
  const visited = new Set();
  const visit = async (filePath) => {
    const resolved = path.resolve(filePath);
    if (visited.has(resolved)) return;
    if (!existsSync(resolved)) throw new Error(`required mutation inventory root is missing: ${resolved}`);
    visited.add(resolved);
    const sourceFile = await parseSource(resolved);
    for (const statement of sourceFile.statements) {
      if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
      const imported = resolveLocalModule(resolved, statement.moduleSpecifier.text);
      if (imported && pathInsideAny(imported, scopeRoots)) await visit(imported);
    }
  };
  for (const root of requiredRoots) await visit(root);
  return visited;
}


function importBindingsForModule(sourceFile, moduleFile, allModuleExports, moduleLabel) {
  const named = new Map();
  const namespaces = new Set();
  for (const statement of sourceFile.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
    const resolved = resolveLocalModule(sourceFile.fileName, statement.moduleSpecifier.text);
    if (!resolved || path.resolve(resolved) !== path.resolve(moduleFile)) continue;
    const clause = statement.importClause;
    if (!clause || clause.isTypeOnly || !clause.namedBindings) continue;
    if (ts.isNamespaceImport(clause.namedBindings)) {
      namespaces.add(clause.namedBindings.name.text);
      continue;
    }
    for (const element of clause.namedBindings.elements) {
      if (element.isTypeOnly) continue;
      const importedName = element.propertyName?.text || element.name.text;
      if (!allModuleExports.has(importedName)) {
        throw new Error(`unknown imported ${moduleLabel} export ${importedName} in ${sourceFile.fileName}`);
      }
      named.set(element.name.text, importedName);
    }
  }
  return { named, namespaces };
}


function propertyNameText(name) {
  if (!name) return null;
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) return name.text;
  return null;
}


function enclosingNamedHandler(node) {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isFunctionDeclaration(current) && current.name) return current.name.text;
    if (
      (ts.isArrowFunction(current) || ts.isFunctionExpression(current))
      && ts.isVariableDeclaration(current.parent)
      && ts.isIdentifier(current.parent.name)
    ) {
      return current.parent.name.text;
    }
    if (ts.isMethodDeclaration(current)) {
      const name = propertyNameText(current.name);
      if (name) return name;
    }
    if (
      (ts.isArrowFunction(current) || ts.isFunctionExpression(current))
      && ts.isPropertyAssignment(current.parent)
    ) {
      const name = propertyNameText(current.parent.name);
      if (name) return name;
    }
  }
  return null;
}


function referencedImportedExport(expression, bindings, allowedExportNames) {
  if (ts.isIdentifier(expression)) {
    const importedName = bindings.named.get(expression.text);
    return importedName && allowedExportNames.has(importedName) ? importedName : null;
  }
  if (
    ts.isPropertyAccessExpression(expression)
    && ts.isIdentifier(expression.expression)
    && bindings.namespaces.has(expression.expression.text)
  ) {
    const importedName = expression.name.text;
    return allowedExportNames.has(importedName) ? importedName : null;
  }
  return null;
}


function calledImportedExport(call, bindings, allowedExportNames) {
  return referencedImportedExport(call.expression, bindings, allowedExportNames);
}


function findExportedObject(sourceFile, exportName) {
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement) || !hasExportModifier(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || declaration.name.text !== exportName) continue;
      const object = unwrapObjectExpression(declaration.initializer);
      if (!object) throw new Error(`${exportName} must be an object literal`);
      return object;
    }
  }
  throw new Error(`${exportName} export is missing`);
}


function findExportedFunction(sourceFile, exportName) {
  const matches = sourceFile.statements.filter(
    (statement) => ts.isFunctionDeclaration(statement)
      && hasExportModifier(statement)
      && statement.name?.text === exportName,
  );
  if (matches.length !== 1 || !matches[0].body) {
    throw new Error(`${exportName} must be exactly one exported function declaration`);
  }
  return matches[0];
}


function unwrapExpression(expression) {
  let current = expression;
  while (
    current
    && (ts.isParenthesizedExpression(current)
      || ts.isAsExpression(current)
      || ts.isSatisfiesExpression(current)
      || ts.isNonNullExpression(current))
  ) {
    current = current.expression;
  }
  return current;
}


function accessPropertyName(expression) {
  if (ts.isPropertyAccessExpression(expression)) return expression.name.text;
  if (ts.isElementAccessExpression(expression)) {
    const argument = unwrapExpression(expression.argumentExpression);
    if (ts.isStringLiteral(argument) || ts.isNoSubstitutionTemplateLiteral(argument)) return argument.text;
  }
  return null;
}


function workflowDispatcherBoundExecuteCall(dispatchFunction) {
  const aliases = new Map([[WORKFLOW_BINDINGS_EXPORT, new Set(['registry'])]]);
  let boundExecuteCall = null;

  const expressionTaints = (input) => {
    const expression = unwrapExpression(input);
    if (!expression) return new Set();
    if (ts.isIdentifier(expression)) return new Set(aliases.get(expression.text) || []);
    if (ts.isPropertyAccessExpression(expression) || ts.isElementAccessExpression(expression)) {
      const baseTaints = expressionTaints(expression.expression);
      if (baseTaints.has('registry')) return new Set(['binding']);
      if (baseTaints.has('binding') && accessPropertyName(expression) === 'execute') {
        return new Set(['execute']);
      }
      return new Set();
    }
    if (
      ts.isBinaryExpression(expression)
      && (expression.operatorToken.kind === ts.SyntaxKind.BarBarToken
        || expression.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken)
    ) {
      return new Set([
        ...expressionTaints(expression.left),
        ...expressionTaints(expression.right),
      ]);
    }
    if (ts.isConditionalExpression(expression)) {
      return new Set([
        ...expressionTaints(expression.whenTrue),
        ...expressionTaints(expression.whenFalse),
      ]);
    }
    return new Set();
  };

  const assignAlias = (name, taints) => {
    if (taints.size) aliases.set(name, taints);
    else aliases.delete(name);
  };

  const visit = (node) => {
    if (boundExecuteCall) return;
    if (node !== dispatchFunction && ts.isFunctionLike(node)) return;
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
      assignAlias(node.name.text, expressionTaints(node.initializer));
      if (node.initializer) visit(node.initializer);
      return;
    }
    if (
      ts.isBinaryExpression(node)
      && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
      && ts.isIdentifier(node.left)
    ) {
      visit(node.right);
      assignAlias(node.left.text, expressionTaints(node.right));
      return;
    }
    if (ts.isCallExpression(node) && expressionTaints(node.expression).has('execute')) {
      boundExecuteCall = node;
      return;
    }
    ts.forEachChild(node, visit);
  };

  visit(dispatchFunction.body);
  return boundExecuteCall;
}


function collectWorkflowRegistry(sourceFile, apiFile, allApiExports, mutatingExportNames) {
  const workflowExports = collectAllExportNames(sourceFile);
  const dispatchFunction = findExportedFunction(sourceFile, WORKFLOW_DISPATCH_EXPORT);
  const boundExecuteCall = workflowDispatcherBoundExecuteCall(dispatchFunction);
  if (!boundExecuteCall) {
    throw new Error(
      `${WORKFLOW_DISPATCH_EXPORT} must call an execute derived from a ${WORKFLOW_BINDINGS_EXPORT} binding lookup`,
    );
  }
  const mutationMetadataArgument = unwrapExpression(boundExecuteCall.arguments[1]);
  if (
    !mutationMetadataArgument
    || !ts.isPropertyAccessExpression(mutationMetadataArgument)
    || !ts.isIdentifier(mutationMetadataArgument.expression)
    || mutationMetadataArgument.expression.text !== 'context'
    || mutationMetadataArgument.name.text !== 'mutationMetadata'
  ) {
    throw new Error(`${WORKFLOW_DISPATCH_EXPORT} must pass context.mutationMetadata to the bound execute`);
  }
  const apiBindings = importBindingsForModule(sourceFile, apiFile, allApiExports, 'API');
  const bindingsObject = findExportedObject(sourceFile, WORKFLOW_BINDINGS_EXPORT);
  const clients = [];
  for (const property of bindingsObject.properties) {
    if (!ts.isPropertyAssignment(property)) {
      throw new Error(`${WORKFLOW_BINDINGS_EXPORT} may contain only explicit property assignments`);
    }
    const bindingName = propertyNameText(property.name);
    const bindingObject = unwrapObjectExpression(property.initializer);
    if (!bindingName || !bindingObject) {
      throw new Error(`${WORKFLOW_BINDINGS_EXPORT} entries must use static keys and object values`);
    }
    const executeProperties = bindingObject.properties.filter(
      (entry) => ts.isPropertyAssignment(entry) && propertyNameText(entry.name) === 'execute',
    );
    if (executeProperties.length !== 1) {
      throw new Error(`${WORKFLOW_BINDINGS_EXPORT}.${bindingName} must contain exactly one execute property`);
    }
    const importedClient = referencedImportedExport(
      executeProperties[0].initializer,
      apiBindings,
      allApiExports,
    );
    if (!importedClient) {
      throw new Error(`${WORKFLOW_BINDINGS_EXPORT}.${bindingName}.execute must reference a static API import`);
    }
    if (!mutatingExportNames.has(importedClient)) {
      throw new Error(`${WORKFLOW_BINDINGS_EXPORT}.${bindingName}.execute is not a mutating API export`);
    }
    if (bindingName !== importedClient) {
      throw new Error(
        `${WORKFLOW_BINDINGS_EXPORT} key ${bindingName} must match execute API export ${importedClient}`,
      );
    }
    clients.push(importedClient);
  }
  if (new Set(clients).size !== clients.length) {
    throw new Error(`${WORKFLOW_BINDINGS_EXPORT} contains duplicate mutation clients`);
  }
  return {
    clients: clients.sort(),
    dispatchExport: WORKFLOW_DISPATCH_EXPORT,
    exports: workflowExports,
  };
}


function validateAllowlist(mutatingExports, usedClients, allowlist) {
  const exportNames = new Set(mutatingExports.map((item) => item.client));
  const allowlistNames = Object.keys(allowlist).sort();
  const unknown = allowlistNames.filter((name) => !exportNames.has(name));
  if (unknown.length) throw new Error(`unknown allowlist exports: ${unknown.join(', ')}`);
  const stale = allowlistNames.filter((name) => usedClients.has(name));
  if (stale.length) throw new Error(`allowlist exports now have owner callsites: ${stale.join(', ')}`);
  for (const name of allowlistNames) {
    const entry = allowlist[name];
    if (!entry || !ALLOWLIST_CLASSIFICATIONS.has(entry.classification) || !String(entry.reason || '').trim()) {
      throw new Error(`invalid allowlist classification/reason for ${name}`);
    }
  }
  const unclassified = mutatingExports
    .map((item) => item.client)
    .filter((name) => !usedClients.has(name) && !Object.hasOwn(allowlist, name));
  if (unclassified.length) throw new Error(`unclassified mutating exports: ${unclassified.join(', ')}`);
  return allowlistNames.map((client) => ({ client, ...allowlist[client] }));
}


function unwrapObjectExpression(initializer) {
  let current = initializer;
  while (
    current
    && (ts.isSatisfiesExpression(current) || ts.isAsExpression(current) || ts.isParenthesizedExpression(current))
  ) {
    current = current.expression;
  }
  return current && ts.isObjectLiteralExpression(current) ? current : null;
}


function staticNonEmptyString(initializer) {
  if (!ts.isStringLiteral(initializer) && !ts.isNoSubstitutionTemplateLiteral(initializer)) return null;
  return initializer.text.trim() ? initializer.text : null;
}


function validateOwnerContractEntry(id, initializer) {
  const object = unwrapObjectExpression(initializer);
  if (!object) throw new Error(`mutation owner contract entry ${id} must be an object literal`);
  const seen = new Set();
  for (const property of object.properties) {
    if (!ts.isPropertyAssignment(property)) {
      throw new Error(`mutation owner contract entry ${id} may contain only explicit property assignments`);
    }
    const field = propertyNameText(property.name);
    if (!field || !OWNER_CONTRACT_FIELDS.has(field)) {
      throw new Error(`mutation owner contract entry ${id} has unknown field ${field || '<dynamic>'}`);
    }
    if (seen.has(field)) throw new Error(`mutation owner contract entry ${id} contains duplicate field ${field}`);
    if (!staticNonEmptyString(property.initializer)) {
      throw new Error(`mutation owner contract entry ${id}.${field} must be a non-empty static string`);
    }
    seen.add(field);
  }
  const missing = [...OWNER_CONTRACT_FIELDS].filter((field) => !seen.has(field));
  if (missing.length) {
    throw new Error(`mutation owner contract entry ${id} is missing fields: ${missing.join(', ')}`);
  }
}


function ownerContractEntryValues(id, initializer) {
  validateOwnerContractEntry(id, initializer);
  const object = unwrapObjectExpression(initializer);
  const values = {};
  for (const property of object.properties) {
    values[propertyNameText(property.name)] = staticNonEmptyString(property.initializer);
  }
  return values;
}


async function ownerContractEntries(contractFile) {
  if (!existsSync(contractFile)) throw new Error(`owner contract is missing: ${contractFile}`);
  const sourceFile = await parseSource(contractFile);
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement) || !hasExportModifier(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || declaration.name.text !== 'mutationOwnerContract') continue;
      const object = unwrapObjectExpression(declaration.initializer);
      if (!object) throw new Error('mutation owner contract must be an object literal');
      const entries = new Map();
      for (const property of object.properties) {
        if (!ts.isPropertyAssignment(property)) {
          throw new Error('mutation owner contract may contain only explicit property assignments');
        }
        const name = propertyNameText(property.name);
        if (!name) throw new Error('mutation owner contract keys must be static strings');
        if (entries.has(name)) throw new Error('mutation owner contract contains duplicate ids');
        entries.set(name, ownerContractEntryValues(name, property.initializer));
      }
      return entries;
    }
  }
  throw new Error('mutationOwnerContract export is missing');
}


async function assertOwnerContractCoverage(contractFile, callsites) {
  const inventoryIds = callsites.map((item) => item.id).sort();
  const entries = await ownerContractEntries(contractFile);
  const contractIds = [...entries.keys()].sort();
  const inventorySet = new Set(inventoryIds);
  const contractSet = new Set(contractIds);
  const missing = inventoryIds.filter((id) => !contractSet.has(id));
  const extra = contractIds.filter((id) => !inventorySet.has(id));
  if (missing.length || extra.length) {
    throw new Error(
      `mutation owner contract ids do not match inventory; missing=[${missing.join(', ')}] extra=[${extra.join(', ')}]`,
    );
  }
  return entries;
}


function findVariableObject(sourceFile, variableName) {
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || declaration.name.text !== variableName) continue;
      return unwrapObjectExpression(declaration.initializer);
    }
  }
  return null;
}


function functionLikeExpression(expression) {
  const unwrapped = unwrapExpression(expression);
  return unwrapped && (ts.isArrowFunction(unwrapped) || ts.isFunctionExpression(unwrapped))
    ? unwrapped
    : null;
}


function objectProperty(object, propertyName) {
  if (!object) return null;
  const matches = object.properties.filter(
    (property) => ts.isPropertyAssignment(property) && propertyNameText(property.name) === propertyName,
  );
  if (matches.length !== 1) return null;
  return matches[0];
}


function collectCalls(node, predicate) {
  const calls = [];
  const visit = (child) => {
    if (ts.isCallExpression(child) && predicate(child)) calls.push(child);
    ts.forEachChild(child, visit);
  };
  visit(node);
  return calls;
}


function isFunctionLikeNode(node) {
  return ts.isArrowFunction(node)
    || ts.isFunctionExpression(node)
    || ts.isFunctionDeclaration(node)
    || ts.isMethodDeclaration(node)
    || ts.isGetAccessorDeclaration(node)
    || ts.isSetAccessorDeclaration(node)
    || ts.isConstructorDeclaration(node);
}


function collectCallsInCallback(functionNode, predicate) {
  const calls = [];
  const visit = (child) => {
    if (isFunctionLikeNode(child)) return;
    if (ts.isCallExpression(child) && predicate(child)) calls.push(child);
    ts.forEachChild(child, visit);
  };
  visit(functionNode.body);
  return calls;
}


function functionParameterName(functionNode, index = 0) {
  const parameter = functionNode.parameters[index];
  return parameter && ts.isIdentifier(parameter.name) ? parameter.name.text : null;
}


function callHasIdentifierArgument(call, identifierName) {
  return call.arguments.some((argument) => {
    const expression = unwrapExpression(argument);
    return ts.isIdentifier(expression) && expression.text === identifierName;
  });
}


function isAnyMessageErrorCall(call) {
  return ts.isPropertyAccessExpression(call.expression)
    && ts.isIdentifier(call.expression.expression)
    && call.expression.expression.text === 'message'
    && call.expression.name.text === 'error';
}


function isMessageErrorCall(call, messageParameterName) {
  return isAnyMessageErrorCall(call)
    && call.arguments.length === 1
    && ts.isIdentifier(unwrapExpression(call.arguments[0]))
    && unwrapExpression(call.arguments[0]).text === messageParameterName;
}


function isIdentifierCall(call, identifierName) {
  return ts.isIdentifier(call.expression) && call.expression.text === identifierName;
}


function loadingStateIdentifier(entry, id) {
  const match = entry.loading_state.match(/^[A-Za-z_$][\w$]*/);
  if (!match) throw new Error(`mutation owner contract entry ${id}.loading_state must start with a state identifier`);
  return match[0];
}


function setterForState(stateName) {
  return `set${stateName[0].toUpperCase()}${stateName.slice(1)}`;
}


function useStateCall(expression) {
  const unwrapped = unwrapExpression(expression);
  return unwrapped && ts.isCallExpression(unwrapped)
    && (
      (ts.isIdentifier(unwrapped.expression) && unwrapped.expression.text === 'useState')
      || (
        ts.isPropertyAccessExpression(unwrapped.expression)
        && unwrapped.expression.name.text === 'useState'
      )
    )
    ? unwrapped
    : null;
}


function loadingClearValue(sourceFile, stateName, setterName, id) {
  const matches = [];
  const visit = (node) => {
    if (ts.isVariableDeclaration(node) && ts.isArrayBindingPattern(node.name)) {
      const [stateElement, setterElement] = node.name.elements;
      const stateIdentifier = stateElement
        && ts.isBindingElement(stateElement)
        && ts.isIdentifier(stateElement.name)
        ? stateElement.name.text
        : null;
      const setterIdentifier = setterElement
        && ts.isBindingElement(setterElement)
        && ts.isIdentifier(setterElement.name)
        ? setterElement.name.text
        : null;
      if (stateIdentifier === stateName && setterIdentifier === setterName) {
        const call = useStateCall(node.initializer);
        if (!call || call.arguments.length !== 1) {
          throw new Error(`mutation owner contract entry ${id}.loading_state must use an explicit useState clear value`);
        }
        const initialValue = unwrapExpression(call.arguments[0]);
        if (initialValue.kind === ts.SyntaxKind.FalseKeyword) matches.push('false');
        else if (initialValue.kind === ts.SyntaxKind.NullKeyword) matches.push('null');
        else {
          throw new Error(
            `mutation owner contract entry ${id}.loading_state must initialize ${stateName} with false or null`,
          );
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  if (matches.length !== 1) {
    throw new Error(
      `mutation owner contract entry ${id}.loading_state must resolve one ${stateName}/${setterName} useState pair`,
    );
  }
  return matches[0];
}


function callUsesClearValue(call, clearValue) {
  if (call.arguments.length !== 1) return false;
  const argument = unwrapExpression(call.arguments[0]);
  return clearValue === 'false'
    ? argument.kind === ts.SyntaxKind.FalseKeyword
    : argument.kind === ts.SyntaxKind.NullKeyword;
}


function swallowsRunnerRethrow(catchCall) {
  if (catchCall.arguments.length !== 1) return false;
  const handler = functionLikeExpression(catchCall.arguments[0]);
  if (!handler || handler.parameters.length !== 0 || ts.isBlock(handler.body)) return false;
  const body = unwrapExpression(handler.body);
  return ts.isIdentifier(body) && body.text === 'undefined';
}


function verifyOwnerContractPolicy(id, entry, sourceIdentifiers, seenPlaywrightCases) {
  if (!entry.catch_policy.includes('apiErrorMessage') || !entry.catch_policy.includes('message.error')) {
    throw new Error(`mutation owner contract entry ${id}.catch_policy must name apiErrorMessage and message.error`);
  }
  if (!entry.finally_policy.includes('runMutationWithUX') || !entry.finally_policy.includes('clearLoading')) {
    throw new Error(`mutation owner contract entry ${id}.finally_policy must name runMutationWithUX clearLoading`);
  }
  if (!entry.playwright_case.startsWith('runtime case:')) {
    throw new Error(`mutation owner contract entry ${id}.playwright_case must be a stable runtime case`);
  }
  if (seenPlaywrightCases.has(entry.playwright_case)) {
    throw new Error(`mutation owner contract playwright_case must be unique: ${entry.playwright_case}`);
  }
  seenPlaywrightCases.add(entry.playwright_case);
  if (!sourceIdentifiers.has(entry.owner_component)) {
    throw new Error(`mutation owner contract entry ${id}.owner_component is not present in its source`);
  }
  const ownerTokens = entry.owner_state.match(/[A-Za-z_$][\w$]*/g) || [];
  if (!ownerTokens.some((token) => sourceIdentifiers.has(token))) {
    throw new Error(`mutation owner contract entry ${id}.owner_state has no live source identifier`);
  }
  const loadingState = loadingStateIdentifier(entry, id);
  const loadingSetter = setterForState(loadingState);
  if (!sourceIdentifiers.has(loadingState) || !sourceIdentifiers.has(loadingSetter)) {
    throw new Error(`mutation owner contract entry ${id}.loading_state must reference live ${loadingState}/${loadingSetter}`);
  }
  if (!entry.finally_policy.includes(loadingState)) {
    throw new Error(`mutation owner contract entry ${id}.finally_policy must reference ${loadingState}`);
  }
  return loadingSetter;
}


function verifyWrapperOwners(wrapperCall, id, entry, sourceFile, sourceIdentifiers, seenPlaywrightCases) {
  const owners = unwrapObjectExpression(wrapperCall.arguments[2]);
  if (!owners) throw new Error(`mutation wrapper ${id} must pass an explicit owners object`);
  const errorFallback = objectProperty(owners, 'errorFallback');
  if (!errorFallback || !staticNonEmptyString(errorFallback.initializer)) {
    throw new Error(`mutation wrapper ${id} must provide a static non-empty errorFallback`);
  }
  const onErrorProperty = objectProperty(owners, 'onError');
  const onError = onErrorProperty && functionLikeExpression(onErrorProperty.initializer);
  const messageParameter = onError && functionParameterName(onError);
  const messageErrorCalls = onError
    ? collectCallsInCallback(onError, isAnyMessageErrorCall)
    : [];
  if (
    !onError
    || !messageParameter
    || messageErrorCalls.length !== 1
    || !isMessageErrorCall(messageErrorCalls[0], messageParameter)
  ) {
    throw new Error(`mutation wrapper ${id}.onError must call message.error(messageParam) once in the callback body`);
  }
  const loadingSetter = verifyOwnerContractPolicy(id, entry, sourceIdentifiers, seenPlaywrightCases);
  const loadingState = loadingStateIdentifier(entry, id);
  const clearValue = loadingClearValue(sourceFile, loadingState, loadingSetter, id);
  const clearLoadingProperty = objectProperty(owners, 'clearLoading');
  const clearLoading = clearLoadingProperty && functionLikeExpression(clearLoadingProperty.initializer);
  const clearCalls = clearLoading
    ? collectCallsInCallback(clearLoading, (call) => isIdentifierCall(call, loadingSetter))
    : [];
  if (clearCalls.length !== 1 || !callUsesClearValue(clearCalls[0], clearValue)) {
    throw new Error(`mutation wrapper ${id}.clearLoading must call ${loadingSetter}(${clearValue}) once in the callback body`);
  }
  const catchAccess = wrapperCall.parent;
  const catchCall = catchAccess?.parent;
  if (
    !ts.isPropertyAccessExpression(catchAccess)
    || catchAccess.name.text !== 'catch'
    || !ts.isCallExpression(catchCall)
    || catchCall.expression !== catchAccess
    || !swallowsRunnerRethrow(catchCall)
  ) {
    throw new Error(`mutation wrapper ${id} must swallow the runner rethrow with .catch(() => undefined)`);
  }
}


function sourceIdentifierSet(sourceFile) {
  const identifiers = new Set();
  const visit = (node) => {
    if (ts.isIdentifier(node)) identifiers.add(node.text);
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return identifiers;
}


function findMutationConfigCall(node, metadataName) {
  return collectCalls(node, (call) => (
    ts.isIdentifier(call.expression)
    && call.expression.text === 'mutationRequestConfig'
    && callHasIdentifierArgument(call, metadataName)
  ));
}


async function assertMutationExportMetadataCoverage(apiFile, mutatingExports) {
  const sourceFile = await parseSource(apiFile);
  const expected = new Set(mutatingExports.map((item) => item.client));
  const verified = new Set();
  for (const statement of sourceFile.statements) {
    if (!hasExportModifier(statement)) continue;
    const functions = [];
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || !expected.has(declaration.name.text)) continue;
        const functionNode = functionLikeExpression(declaration.initializer);
        if (functionNode) functions.push({ name: declaration.name.text, functionNode });
      }
    } else if (ts.isFunctionDeclaration(statement) && statement.name && expected.has(statement.name.text)) {
      functions.push({ name: statement.name.text, functionNode: statement });
    }
    for (const { name, functionNode } of functions) {
      const metadataParameter = functionNode.parameters.find(
        (parameter) => ts.isIdentifier(parameter.name) && parameter.name.text === 'metadata',
      );
      if (!metadataParameter) throw new Error(`mutating export ${name} must accept metadata`);
      if (findMutationConfigCall(functionNode.body, 'metadata').length === 0) {
        throw new Error(`mutating export ${name} must pass metadata through mutationRequestConfig`);
      }
      verified.add(name);
    }
  }
  const missing = [...expected].filter((name) => !verified.has(name));
  if (missing.length) throw new Error(`mutating exports missing metadata coverage: ${missing.join(', ')}`);
}


function workflowCallsiteMap(sourceFile, mapName) {
  const object = findVariableObject(sourceFile, mapName);
  if (!object) throw new Error(`workflow mutation wrapper map ${mapName} must be an object literal`);
  const entries = new Map();
  for (const property of object.properties) {
    if (!ts.isPropertyAssignment(property)) {
      throw new Error(`workflow mutation wrapper map ${mapName} may contain only explicit entries`);
    }
    const client = propertyNameText(property.name);
    const id = staticNonEmptyString(property.initializer);
    if (!client || !id) throw new Error(`workflow mutation wrapper map ${mapName} requires static client/id entries`);
    if (entries.has(client)) throw new Error(`workflow mutation wrapper map ${mapName} contains duplicate client ${client}`);
    entries.set(client, id);
  }
  return entries;
}


function workflowWrapperMapName(expression) {
  const unwrapped = unwrapExpression(expression);
  if (!ts.isElementAccessExpression(unwrapped) || !ts.isIdentifier(unwrapped.expression)) return null;
  const selector = unwrapExpression(unwrapped.argumentExpression);
  if (
    !ts.isPropertyAccessExpression(selector)
    || selector.name.text !== 'client_export'
  ) {
    return null;
  }
  return unwrapped.expression.text;
}


function dispatchPassesMutationMetadata(call, metadataName) {
  const context = unwrapObjectExpression(call.arguments[1]);
  const property = objectProperty(context, 'mutationMetadata');
  const initializer = property && unwrapExpression(property.initializer);
  return Boolean(initializer && ts.isIdentifier(initializer) && initializer.text === metadataName);
}


async function assertStaticWrapperCoverage(analysis, ownerEntries, options = {}) {
  const mutationRunnerFile = path.resolve(
    options.mutationRunnerFile || path.join(analysis.frontendRoot, 'src/api/mutationRunner.ts'),
  );
  if (!existsSync(mutationRunnerFile)) throw new Error(`mutation runner is missing: ${mutationRunnerFile}`);
  await assertMutationExportMetadataCoverage(analysis.apiFile, analysis.mutatingExports);
  const inventoryById = new Map(analysis.callsites.map((callsite) => [callsite.id, callsite]));
  const workflowClients = new Set(analysis.workflowMutationClients);
  const verifiedIds = new Set();
  const seenPlaywrightCases = new Set();
  const sourceFiles = [...new Set(analysis.callsites.map((callsite) => callsite.source))].sort();

  for (const relativeSource of sourceFiles) {
    const filePath = path.resolve(analysis.repoRoot, relativeSource);
    const sourceFile = await parseSource(filePath);
    const sourceIdentifiers = sourceIdentifierSet(sourceFile);
    const apiExports = collectAllExportNames(await parseSource(analysis.apiFile));
    const apiBindings = importBindingsForModule(
      sourceFile,
      analysis.apiFile,
      apiExports,
      'API',
    );
    const runnerBindings = importBindingsForModule(
      sourceFile,
      mutationRunnerFile,
      new Set(['runMutationWithUX']),
      'mutation runner',
    );
    const workflowExports = collectAllExportNames(await parseSource(analysis.workflowRegistryFile));
    const workflowBindings = importBindingsForModule(
      sourceFile,
      analysis.workflowRegistryFile,
      workflowExports,
      'workflow registry',
    );
    const wrapperCalls = collectCalls(sourceFile, (call) => (
      calledImportedExport(call, runnerBindings, new Set(['runMutationWithUX'])) === 'runMutationWithUX'
    ));

    for (const wrapperCall of wrapperCalls) {
      const handler = enclosingNamedHandler(wrapperCall);
      if (!handler) throw new Error(`mutation wrapper has no enclosing named handler: ${relativeSource}`);
      const operation = functionLikeExpression(wrapperCall.arguments[1]);
      const metadataName = operation && functionParameterName(operation);
      if (!operation || !metadataName) {
        throw new Error(`mutation wrapper in ${relativeSource}|${handler} must accept metadata in its operation`);
      }
      const literalId = staticNonEmptyString(unwrapExpression(wrapperCall.arguments[0]));
      if (literalId) {
        const callsite = inventoryById.get(literalId);
        if (!callsite || callsite.via !== 'direct') {
          throw new Error(`mutation wrapper uses unknown or non-direct callsite id ${literalId}`);
        }
        if (callsite.source !== relativeSource || callsite.handler !== handler) {
          throw new Error(`mutation wrapper ${literalId} is attached to ${relativeSource}|${handler}`);
        }
        const apiCalls = collectCallsInCallback(operation, (call) => (
          calledImportedExport(call, apiBindings, new Set([callsite.client])) === callsite.client
        ));
        if (apiCalls.length !== 1 || !callHasIdentifierArgument(apiCalls[0], metadataName)) {
          throw new Error(`mutation wrapper ${literalId} must call ${callsite.client} once with operation metadata`);
        }
        const entry = ownerEntries.get(literalId);
        if (!entry) throw new Error(`mutation wrapper ${literalId} is missing its owner contract`);
        verifyWrapperOwners(wrapperCall, literalId, entry, sourceFile, sourceIdentifiers, seenPlaywrightCases);
        if (verifiedIds.has(literalId)) throw new Error(`mutation wrapper id is duplicated: ${literalId}`);
        verifiedIds.add(literalId);
        continue;
      }

      const mapName = workflowWrapperMapName(wrapperCall.arguments[0]);
      if (!mapName) throw new Error(`mutation wrapper in ${relativeSource}|${handler} must use a static id or workflow client map`);
      const mappedCallsites = workflowCallsiteMap(sourceFile, mapName);
      const mappedClients = new Set(mappedCallsites.keys());
      const missingClients = [...workflowClients].filter((client) => !mappedClients.has(client));
      const extraClients = [...mappedClients].filter((client) => !workflowClients.has(client));
      if (missingClients.length || extraClients.length) {
        throw new Error(
          `workflow mutation wrapper map ${mapName} client mismatch; missing=[${missingClients.join(', ')}] extra=[${extraClients.join(', ')}]`,
        );
      }
      const dispatchCalls = collectCallsInCallback(operation, (call) => (
        calledImportedExport(call, workflowBindings, new Set([WORKFLOW_DISPATCH_EXPORT])) === WORKFLOW_DISPATCH_EXPORT
      ));
      if (dispatchCalls.length !== 1 || !dispatchPassesMutationMetadata(dispatchCalls[0], metadataName)) {
        throw new Error(`workflow mutation wrapper ${relativeSource}|${handler} must dispatch once with mutationMetadata`);
      }
      for (const [client, id] of mappedCallsites) {
        const callsite = inventoryById.get(id);
        if (
          !callsite
          || callsite.via !== 'workflow_registry'
          || callsite.client !== client
          || callsite.source !== relativeSource
          || callsite.handler !== handler
        ) {
          throw new Error(`workflow mutation wrapper map ${mapName}.${client} does not match inventory id ${id}`);
        }
        const entry = ownerEntries.get(id);
        if (!entry) throw new Error(`workflow mutation wrapper ${id} is missing its owner contract`);
        verifyWrapperOwners(wrapperCall, id, entry, sourceFile, sourceIdentifiers, seenPlaywrightCases);
        if (verifiedIds.has(id)) throw new Error(`mutation wrapper id is duplicated: ${id}`);
        verifiedIds.add(id);
      }
    }
  }

  const inventoryIds = analysis.callsites.map((item) => item.id).sort();
  const contractIds = [...ownerEntries.keys()].sort();
  const staticIds = [...verifiedIds].sort();
  const missingStatic = inventoryIds.filter((id) => !verifiedIds.has(id));
  const extraStatic = staticIds.filter((id) => !inventoryById.has(id));
  if (
    inventoryIds.join('\n') !== contractIds.join('\n')
    || missingStatic.length
    || extraStatic.length
  ) {
    throw new Error(
      `mutation static coverage mismatch; missing=[${missingStatic.join(', ')}] extra=[${extraStatic.join(', ')}]`,
    );
  }
  return staticIds;
}


export async function analyzeMutationInventory(options = {}) {
  const frontendRoot = path.resolve(options.frontendRoot || defaultFrontendRoot);
  const repoRoot = path.resolve(options.repoRoot || defaultRepoRoot);
  const apiFile = path.resolve(options.apiFile || path.join(frontendRoot, 'src/api/index.ts'));
  const workflowRegistryFile = path.resolve(
    options.workflowRegistryFile || path.join(frontendRoot, 'src/workflow/productWorkflowActionRegistry.ts'),
  );
  const requiredRoots = (options.requiredRoots || DEFAULT_REQUIRED_ROOTS.map((item) => path.join(frontendRoot, item)))
    .map((item) => path.resolve(item));
  const allowlist = options.allowlist || {};
  const apiSource = await parseSource(apiFile);
  const allApiExports = collectAllExportNames(apiSource);
  const mutatingExports = collectMutatingExports(apiSource);
  const mutationByName = new Map(mutatingExports.map((item) => [item.client, item]));
  const mutatingExportNames = new Set(mutationByName.keys());
  const workflowRegistrySource = await parseSource(workflowRegistryFile);
  const workflowRegistry = collectWorkflowRegistry(
    workflowRegistrySource,
    apiFile,
    allApiExports,
    mutatingExportNames,
  );
  const workflowDispatchExports = new Set([workflowRegistry.dispatchExport]);
  const scopeRoots = SCAN_DIRECTORIES.map((item) => path.join(frontendRoot, item));
  const scanFiles = (await Promise.all(scopeRoots.map(listTypeScriptFiles))).flat().sort();
  const requiredReachableFiles = await collectRequiredReachableFiles(requiredRoots, scopeRoots);
  const rawCalls = [];
  const workflowOwnerKeys = new Set();

  for (const filePath of scanFiles) {
    const sourceFile = await parseSource(filePath);
    const apiBindings = importBindingsForModule(sourceFile, apiFile, allApiExports, 'API');
    const workflowBindings = importBindingsForModule(
      sourceFile,
      workflowRegistryFile,
      workflowRegistry.exports,
      'workflow registry',
    );
    const visit = (node) => {
      if (ts.isCallExpression(node)) {
        const client = calledImportedExport(node, apiBindings, mutatingExportNames);
        if (client) {
          const handler = enclosingNamedHandler(node);
          if (!handler) {
            throw new Error(`mutation callsite has no enclosing named handler: ${filePath}:${node.getStart(sourceFile)}`);
          }
          rawCalls.push({
            client,
            source: slash(path.relative(repoRoot, filePath)),
            handler,
            position: node.getStart(sourceFile),
            via: 'direct',
          });
        }
        const workflowDispatch = calledImportedExport(
          node,
          workflowBindings,
          workflowDispatchExports,
        );
        if (workflowDispatch) {
          const handler = enclosingNamedHandler(node);
          if (!handler) {
            throw new Error(`workflow mutation owner has no enclosing named handler: ${filePath}:${node.getStart(sourceFile)}`);
          }
          const source = slash(path.relative(repoRoot, filePath));
          for (const workflowClient of workflowRegistry.clients) {
            const ownerKey = `${workflowClient}|${source}|${handler}`;
            if (workflowOwnerKeys.has(ownerKey)) continue;
            workflowOwnerKeys.add(ownerKey);
            rawCalls.push({
              client: workflowClient,
              source,
              handler,
              position: node.getStart(sourceFile),
              via: 'workflow_registry',
            });
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sourceFile);
  }

  const groups = new Map();
  for (const call of rawCalls) {
    const key = `${call.client}|${call.source}|${call.handler}`;
    const group = groups.get(key) || [];
    group.push(call);
    groups.set(key, group);
  }
  const callsites = [];
  for (const [baseId, group] of groups) {
    group.sort((left, right) => left.position - right.position || left.via.localeCompare(right.via));
    group.forEach((call, index) => {
      const mutation = mutationByName.get(call.client);
      callsites.push({
        id: group.length > 1 ? `${baseId}|${index + 1}` : baseId,
        client: call.client,
        endpoint: mutation.endpoint,
        method: mutation.method,
        source: call.source,
        handler: call.handler,
        via: call.via,
      });
    });
  }
  callsites.sort((left, right) => left.id.localeCompare(right.id));
  const usedClients = new Set(callsites.map((item) => item.client));
  const exceptions = validateAllowlist(mutatingExports, usedClients, allowlist);
  return {
    repoRoot,
    frontendRoot,
    apiFile,
    workflowRegistryFile,
    mutatingExports,
    callsites,
    exceptions,
    workflowMutationClients: workflowRegistry.clients,
    requiredReachableFiles: [...requiredReachableFiles].map((item) => slash(path.relative(repoRoot, item))).sort(),
  };
}


export function renderMutationInventory(analysis, options = {}) {
  const staticWrapperStatus = options.staticWrapperCoverageEnabled ? 'enabled' : 'not-enabled';
  const union = analysis.callsites.length
    ? analysis.callsites.map((item) => `  | ${JSON.stringify(item.id)}`).join('\n')
    : '  never';
  return `/* This file is generated by scripts/generate-mutation-inventory.mjs. */\n`
    + `/* D2b static wrapper coverage: ${staticWrapperStatus}. Runtime Playwright coverage: enabled. */\n\n`
    + `export interface MutationCallsite {\n`
    + `  id: string;\n  client: string;\n  endpoint: string;\n  method: 'post' | 'put' | 'patch' | 'delete';\n  source: string;\n  handler: string;\n  via: 'direct' | 'workflow_registry';\n}\n\n`
    + `export type MutationCallsiteId =\n${union};\n\n`
    + `export const mutationInventory = ${JSON.stringify(analysis.callsites, null, 2)} as const satisfies readonly MutationCallsite[];\n\n`
    + `export const mutationExportExceptions = ${JSON.stringify(analysis.exceptions, null, 2)} as const;\n\n`
    + `export const mutationInventoryFoundationStatus = {\n`
    + `  inventory_owner_contract: 'enabled',\n`
    + `  d2b_static_wrapper_coverage: '${staticWrapperStatus}',\n`
    + `  d2b_runtime_playwright_coverage: 'enabled',\n`
    + `} as const;\n`;
}


export async function generateMutationInventory(options = {}) {
  const frontendRoot = path.resolve(options.frontendRoot || defaultFrontendRoot);
  const outputFile = path.resolve(options.outputFile || path.join(frontendRoot, 'src/api/mutationInventory.generated.ts'));
  const ownerContractFile = path.resolve(options.ownerContractFile || path.join(frontendRoot, 'src/api/mutationOwnerContract.ts'));
  const analysis = await analyzeMutationInventory(options);
  const ownerEntries = await assertOwnerContractCoverage(ownerContractFile, analysis.callsites);
  const staticWrapperCoverageEnabled = options.staticWrapperCoverage !== false;
  if (staticWrapperCoverageEnabled) {
    await assertStaticWrapperCoverage(analysis, ownerEntries, options);
  }
  const generated = renderMutationInventory(analysis, { staticWrapperCoverageEnabled });
  if (options.check) {
    if (!existsSync(outputFile)) throw new Error(`generated mutation inventory is missing: ${outputFile}`);
    const current = await readFile(outputFile, 'utf8');
    if (current !== generated) throw new Error('generated mutation inventory is stale; run npm run mutations:generate');
  } else {
    await mkdir(path.dirname(outputFile), { recursive: true });
    await writeFile(outputFile, generated, 'utf8');
  }
  return analysis;
}


async function runCli() {
  const check = process.argv.includes('--check');
  const analysis = await generateMutationInventory({
    check,
    allowlist: mutationExportAllowlist,
  });
  console.log(
    `Mutation inventory ${check ? 'is fresh' : 'generated'}: `
    + `${analysis.callsites.length} callsites / ${analysis.mutatingExports.length} mutating exports / `
    + `${analysis.exceptions.length} explicit exceptions. D2b static wrapper coverage: enabled.`,
  );
}


if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  runCli().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
